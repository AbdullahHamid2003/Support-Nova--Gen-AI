"""Central prompt management (SRS Steps 48-49): versioned templates stored in prompts/<key>/<version>.yaml,
seeded into the database, editable/activatable by administrators, fingerprinted with sha256."""

from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from supportnova.audit import service as audit
from supportnova.core.errors import NotFound, ValidationFailed
from supportnova.core.paths import PROMPTS_DIR
from supportnova.database.models import Prompt, PromptVersion, User


@dataclass
class PromptTemplate:
    key: str
    version: str
    status: str
    output_schema: str
    system_template: str
    user_template: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    changelog: str = ""
    source: str = "file"

    @property
    def sha256(self) -> str:
        return hashlib.sha256((self.system_template + "\n---\n" + self.user_template).encode("utf-8")).hexdigest()

    def render(self, values: dict[str, Any]) -> tuple[str, str]:
        safe = {k: ("" if v is None else str(v)) for k, v in values.items()}
        return (string.Template(self.system_template).safe_substitute(safe),
                string.Template(self.user_template).safe_substitute(safe))


def load_file_prompts() -> list[PromptTemplate]:
    templates: list[PromptTemplate] = []
    for path in sorted(PROMPTS_DIR.glob("*/*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        templates.append(PromptTemplate(
            key=data["key"], version=str(data["version"]), status=data.get("status", "draft"),
            output_schema=data["output_schema"], system_template=data["system"], user_template=data["user"],
            params=data.get("params") or {}, description=data.get("description", ""),
            changelog=data.get("changelog", ""), source="file"))
    return templates


def seed_prompts(db: Session) -> int:
    added = 0
    for tpl in load_file_prompts():
        prompt = db.execute(select(Prompt).where(Prompt.prompt_key == tpl.key)).scalar_one_or_none()
        if prompt is None:
            prompt = Prompt(prompt_key=tpl.key, description=tpl.description)
            db.add(prompt)
            db.flush()
        exists = db.execute(select(PromptVersion.id).where(PromptVersion.prompt_id == prompt.id,
                                                           PromptVersion.version == tpl.version)).first()
        if not exists:
            if tpl.status == "active":  # a new active version shipped in prompts/ supersedes the current one
                previous = db.execute(select(PromptVersion).where(PromptVersion.prompt_id == prompt.id,
                                                                  PromptVersion.status == "active")).scalars().all()
                for row in previous:
                    row.status = "retired"
                if previous:
                    audit.record(db, action="prompt.activated", entity_type="prompt", entity_id=f"{tpl.key}@{tpl.version}",
                                 actor=None, summary=f"Prompt {tpl.key} {tpl.version} activated from prompts/ "
                                 f"(retired {', '.join(r.version for r in previous)})",
                                 details={"retired": [r.version for r in previous], "sha256": tpl.sha256})
            db.add(PromptVersion(prompt_id=prompt.id, version=tpl.version, status=tpl.status,
                                 system_template=tpl.system_template, user_template=tpl.user_template,
                                 output_schema=tpl.output_schema, params=tpl.params, changelog=tpl.changelog,
                                 sha256=tpl.sha256))
            added += 1
    db.flush()
    return added


def _from_row(key: str, row: PromptVersion, description: str) -> PromptTemplate:
    return PromptTemplate(key=key, version=row.version, status=row.status, output_schema=row.output_schema,
                          system_template=row.system_template, user_template=row.user_template,
                          params=dict(row.params or {}), description=description, changelog=row.changelog,
                          source="db")


def active_prompt(db: Session | None, key: str) -> PromptTemplate:
    if db is not None:
        prompt = db.execute(select(Prompt).options(selectinload(Prompt.versions)).where(Prompt.prompt_key == key)
                            ).scalar_one_or_none()
        if prompt:
            active = [v for v in prompt.versions if v.status == "active"]
            if active:
                return _from_row(key, active[-1], prompt.description)
    files = [t for t in load_file_prompts() if t.key == key and t.status == "active"]
    if not files:
        raise NotFound(f"No active prompt template '{key}'.")
    return files[-1]


def create_version(db: Session, *, key: str, version: str, system_template: str, user_template: str,
                   output_schema: str, params: dict[str, Any], changelog: str, actor: User | None,
                   activate: bool = False) -> PromptVersion:
    prompt = db.execute(select(Prompt).options(selectinload(Prompt.versions)).where(Prompt.prompt_key == key)
                        ).scalar_one_or_none()
    if prompt is None:
        raise NotFound(f"Prompt '{key}' not found.")
    if any(v.version == version for v in prompt.versions):
        raise ValidationFailed(f"Version {version} already exists for prompt '{key}'.")
    for required in ("$complaint", "$nonce"):
        if required not in user_template and required not in system_template:
            raise ValidationFailed(f"Template must contain the {required} placeholder (untrusted-data isolation).")
    tpl = PromptTemplate(key, version, "draft", output_schema, system_template, user_template, params)
    row = PromptVersion(prompt_id=prompt.id, version=version, status="draft", system_template=system_template,
                        user_template=user_template, output_schema=output_schema, params=params, changelog=changelog,
                        sha256=tpl.sha256, created_by_id=actor.id if actor else None)
    db.add(row)
    db.flush()
    audit.record(db, action="prompt.version_created", entity_type="prompt", entity_id=f"{key}@{version}", actor=actor,
                 summary=f"Created prompt {key} v{version}", details={"sha256": tpl.sha256, "changelog": changelog})
    if activate:
        activate_version(db, key=key, version=version, actor=actor)
    return row


def activate_version(db: Session, *, key: str, version: str, actor: User | None) -> PromptVersion:
    prompt = db.execute(select(Prompt).options(selectinload(Prompt.versions)).where(Prompt.prompt_key == key)
                        ).scalar_one_or_none()
    if prompt is None:
        raise NotFound(f"Prompt '{key}' not found.")
    target = next((v for v in prompt.versions if v.version == version), None)
    if target is None:
        raise NotFound(f"Prompt {key} v{version} not found.")
    previous = [v.version for v in prompt.versions if v.status == "active"]
    for v in prompt.versions:
        if v.status == "active" and v is not target:
            v.status = "retired"
    target.status = "active"
    db.flush()
    audit.record(db, action="prompt.activated", entity_type="prompt", entity_id=f"{key}@{version}", actor=actor,
                 summary=f"Activated prompt {key} v{version}", details={"previous_active": previous})
    return target
