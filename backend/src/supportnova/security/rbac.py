"""Role-based access control (SRS 1.6 ii). Permissions are enforced on the backend for every endpoint."""

from __future__ import annotations

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "customer": [
        "complaint:create", "complaint:read_own", "complaint:clarify_own",
    ],
    "agent": [
        "complaint:create", "complaint:read_all", "complaint:update", "complaint:respond", "complaint:reprocess",
        "escalation:create", "knowledge:read", "rules:read", "analytics:read_own", "review:read",
    ],
    "reviewer": [
        "complaint:read_all", "complaint:update", "complaint:respond", "complaint:reprocess", "review:read",
        "review:act", "escalation:create", "knowledge:read", "rules:read", "analytics:read", "reports:export",
        "evaluation:read", "lab:use", "audit:read_complaint",
    ],
    "manager": [
        "complaint:read_all", "complaint:update", "review:read", "review:act", "escalation:create", "knowledge:read",
        "rules:read", "analytics:read", "reports:export", "evaluation:read", "audit:read_complaint", "users:read",
    ],
    "admin": [
        "complaint:create", "complaint:read_all", "complaint:update", "complaint:respond", "complaint:reprocess",
        "review:read", "review:act", "escalation:create", "knowledge:read", "knowledge:manage", "rules:read",
        "rules:manage", "taxonomy:manage", "prompts:manage", "users:read", "users:manage", "analytics:read",
        "reports:export", "evaluation:read", "evaluation:run", "lab:use", "audit:read", "audit:read_complaint",
        "settings:manage",
    ],
}

ROLE_NAMES = {
    "customer": ("Customer", "Submits complaints, tracks status, answers clarification requests."),
    "agent": ("Support Agent", "Works assigned complaints, sends validated responses, escalates."),
    "reviewer": ("Reviewer", "Works the manual review queue: approve, reject, modify, reclassify, regenerate."),
    "manager": ("Support Manager", "Monitors trends, SLA, escalations and validation performance."),
    "admin": ("Administrator", "Manages users, knowledge base, rules, prompts and configuration."),
}
