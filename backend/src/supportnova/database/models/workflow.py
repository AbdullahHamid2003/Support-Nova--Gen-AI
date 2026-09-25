"""Resolutions, customer responses, escalations, follow-ups, manual reviews, audit and evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from supportnova.database.base import Base, TimestampMixin


class Resolution(Base, TimestampMixin):
    __tablename__ = "resolutions"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True)
    ai_steps: Mapped[list[Any]] = mapped_column(default=list)
    validated_steps: Mapped[list[Any]] = mapped_column(default=list)
    eligibility: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|validated|approved|overridden
    source: Mapped[str] = mapped_column(String(16), default="pipeline")  # pipeline | reviewer
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerResponse(Base, TimestampMixin):
    __tablename__ = "customer_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(24), default="response")  # response | follow_up | clarification
    tone: Mapped[str] = mapped_column(String(20), default="professional")
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|ready|requires_review|approved|sent|rejected
    source: Mapped[str] = mapped_column(String(16), default="ai")  # provider name | reviewer | agent
    validation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_via: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Escalation(Base, TimestampMixin):
    __tablename__ = "escalations"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(48))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="rule")  # rule | ai | reviewer | sla
    rule_ids: Mapped[list[Any]] = mapped_column(default=list)
    departments: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|acknowledged|resolved
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FollowUp(Base, TimestampMixin):
    __tablename__ = "follow_ups"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)  # scheduled|sent|completed|cancelled|overdue
    source_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Review(Base, TimestampMixin):
    """Manual review queue item. The original AI output and validation remain untouched."""

    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True)
    validation_result_id: Mapped[int | None] = mapped_column(ForeignKey("validation_results.id", ondelete="SET NULL"),
                                                             nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|in_review|completed
    reason_codes: Mapped[list[Any]] = mapped_column(default=list)
    reasons: Mapped[list[Any]] = mapped_column(default=list)
    priority: Mapped[str | None] = mapped_column(String(4), nullable=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    original_snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)
    final_snapshot: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    actions: Mapped[list[ReviewAction]] = relationship(back_populates="review", order_by="ReviewAction.id",
                                                       cascade="all, delete-orphan")


class ReviewAction(Base, TimestampMixin):
    __tablename__ = "review_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(24))  # approve|reject|modify|reclassify|reassign|escalate|regenerate|comment
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    comment: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[dict[str, Any]] = mapped_column(default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(default=dict)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(120), default="")
    review: Mapped[Review] = relationship(back_populates="actions")


class AuditLog(Base):
    """Append-only, hash-chained audit trail. UPDATE/DELETE are blocked by the ORM and (on PostgreSQL)
    by a database trigger; ``verify_chain`` detects tampering."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(160), default="system")
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(48), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    split: Mapped[str] = mapped_column(String(16), index=True)
    record: Mapped[dict[str, Any]] = mapped_column(default=dict)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    split: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    fault_injection: Mapped[str | None] = mapped_column(String(48), nullable=True)
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ruleset_hash: Mapped[str] = mapped_column(String(32), default="")
    n_cases: Mapped[int] = mapped_column(Integer, default=0)
    n_done: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    report_paths: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(20), index=True)
    difficulty_type: Mapped[str] = mapped_column(String(40), default="")
    expected: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ai: Mapped[dict[str, Any]] = mapped_column(default=dict)
    python: Mapped[dict[str, Any]] = mapped_column(default=dict)
    comparison: Mapped[dict[str, Any]] = mapped_column(default=dict)
    verification_status: Mapped[str] = mapped_column(String(20), default="")
    verification_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
