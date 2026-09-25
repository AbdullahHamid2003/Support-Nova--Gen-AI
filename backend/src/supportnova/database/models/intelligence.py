"""Rules, prompts, AI runs, analyses, policy references and validation results."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from supportnova.database.base import Base, JSONType, TimestampMixin


class RuleRecord(Base, TimestampMixin):
    """Runtime-editable Rule Matrix entry. rule_type in: resolution, escalation, routing,
    conditional_routing, urgency_floor, category, missing_info, sla, review, config."""

    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("rule_type", "rule_id", name="uq_rules_type_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    subcategory_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Prompt(Base, TimestampMixin):
    __tablename__ = "prompts"
    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    versions: Mapped[list[PromptVersion]] = relationship(back_populates="prompt", order_by="PromptVersion.id",
                                                         cascade="all, delete-orphan")


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # active | draft | retired
    system_template: Mapped[str] = mapped_column(Text)
    user_template: Mapped[str] = mapped_column(Text)
    output_schema: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    changelog: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    prompt: Mapped[Prompt] = relationship(back_populates="versions")


class Analysis(Base, TimestampMixin):
    """One Pipeline-1 + Pipeline-2 run for a complaint. Never overwritten (new version_no per run)."""

    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("complaint_id", "version_no", name="uq_analyses_complaint_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(32), default="submission")
    status: Mapped[str] = mapped_column(String(24), default="running")  # running|completed|invalid_output|failed
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    fault_injection: Mapped[str | None] = mapped_column(String(48), nullable=True)
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    policy_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ruleset_hash: Mapped[str] = mapped_column(String(32), default="")
    output: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    communication: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    retrieval: Mapped[dict[str, Any]] = mapped_column(default=dict)
    stage_timings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_runs: Mapped[list[AIRun]] = relationship(back_populates="analysis", order_by="AIRun.id")


class AIRun(Base, TimestampMixin):
    """Every GenAI call attempt (including invalid outputs and retries) - SRS Step 47/49 evidence."""

    __tablename__ = "ai_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int | None] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True, nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True, nullable=True)
    stage: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    prompt_key: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    request: Mapped[dict[str, Any]] = mapped_column(default=dict)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    error_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fault_injection: Mapped[str | None] = mapped_column(String(48), nullable=True)
    analysis: Mapped[Analysis | None] = relationship(back_populates="ai_runs")


class PolicyReference(Base):
    __tablename__ = "policy_references"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    section_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunk_uid: Mapped[str | None] = mapped_column(String(96), nullable=True)
    cited_by: Mapped[str] = mapped_column(String(16))  # ai | rule | retrieval
    applicability: Mapped[str] = mapped_column(String(32))
    is_active_version: Mapped[bool] = mapped_column(Boolean, default=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")


class ValidationResult(Base, TimestampMixin):
    __tablename__ = "validation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), unique=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    overall_status: Mapped[str] = mapped_column(String(8))  # pass | warn | fail
    verification_score: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(20))  # Verified | Manual Review
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    python_expected: Mapped[dict[str, Any]] = mapped_column(default=dict)
    comparison: Mapped[dict[str, Any]] = mapped_column(default=dict)
    validated_decision: Mapped[dict[str, Any]] = mapped_column(default=dict)
    review_reasons: Mapped[list[Any]] = mapped_column(default=list)
    counts: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ruleset_hash: Mapped[str] = mapped_column(String(32), default="")
    checks: Mapped[list[ValidationCheck]] = relationship(back_populates="result", cascade="all, delete-orphan",
                                                         order_by="ValidationCheck.id")


class ValidationCheck(Base):
    __tablename__ = "validation_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("validation_results.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(160))
    dimension: Mapped[str] = mapped_column(String(24), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), index=True)  # pass | warn | fail | not_applicable
    message: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[Any] = mapped_column(JSONType, nullable=True)
    actual: Mapped[Any] = mapped_column(JSONType, nullable=True)
    rule_refs: Mapped[list[Any]] = mapped_column(default=list)
    policy_refs: Mapped[list[Any]] = mapped_column(default=list)
    result: Mapped[ValidationResult] = relationship(back_populates="checks")
