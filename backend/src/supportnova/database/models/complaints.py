"""Complaints, attachments, lifecycle history, simulated orders and SLA records."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from supportnova.database.base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    """Simulated order ledger record (no live commerce/payment integration - SRS 1.4)."""

    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_ref: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True, nullable=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_total: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="delivered")
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Complaint(Base, TimestampMixin):
    __tablename__ = "complaints"
    __table_args__ = (
        Index("ix_complaints_status_created", "status", "created_at"),
        Index("ix_complaints_category_created", "category_code", "created_at"),
        Index("ix_complaints_department_status", "department_code", "status"),
        Index("ix_complaints_customer_created", "customer_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_ref: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="web")  # web | api | dataset | lab | evaluation
    dataset_case_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    # ---- submitted fields (original text is never modified) ------------------------
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    supporting_info: Mapped[str] = mapped_column(Text, default="")
    customer_type: Mapped[str] = mapped_column(String(32), default="individual")
    channel: Mapped[str] = mapped_column(String(32), default="web_form")
    product_text: Mapped[str] = mapped_column(String(200), default="")
    order_ref: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    transaction_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_complaint_ref: Mapped[str | None] = mapped_column(String(20), nullable=True)
    preferred_contact: Mapped[str] = mapped_column(String(20), default="email")
    requested_resolution: Mapped[str] = mapped_column(String(32), default="none")
    requested_tone: Mapped[str] = mapped_column(String(20), default="professional")
    complaint_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ---- preprocessing --------------------------------------------------------------
    description_normalized: Mapped[str] = mapped_column(Text, default="")
    text_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    preprocessing: Mapped[dict[str, Any]] = mapped_column(default=dict)

    # ---- lifecycle & final (validated) intelligence, denormalised for search/analytics -----
    status: Mapped[str] = mapped_column(String(32), default="New", index=True)
    processing_stage: Mapped[str] = mapped_column(String(32), default="queued")
    verification_status: Mapped[str] = mapped_column(String(20), default="Pending", index=True)
    verification_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    category_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subcategory_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    department_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(4), nullable=True, index=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    product_sku: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    escalation_level: Mapped[str | None] = mapped_column(String(48), nullable=True)
    escalation_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sla_state: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    ai_python_agreement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_of_id: Mapped[int | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_agent_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer = relationship("Customer", lazy="joined")
    assigned_agent = relationship("User", foreign_keys=[assigned_agent_id], lazy="joined")
    attachments: Mapped[list[ComplaintAttachment]] = relationship(back_populates="complaint", cascade="all, delete-orphan")


class ComplaintAttachment(Base, TimestampMixin):
    __tablename__ = "complaint_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    storage_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    complaint: Mapped[Complaint] = relationship(back_populates="attachments")


class ComplaintHistory(Base, TimestampMixin):
    """Lifecycle / timeline events shown in the complaint audit trail."""

    __tablename__ = "complaint_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(120), default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)


class SlaRecord(Base):
    __tablename__ = "sla_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), unique=True)
    priority: Mapped[str] = mapped_column(String(4))
    rule_id: Mapped[str] = mapped_column(String(16), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_state: Mapped[str] = mapped_column(String(16), default="On Track")
    resolution_state: Mapped[str] = mapped_column(String(16), default="On Track", index=True)
    at_risk_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    breach_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
