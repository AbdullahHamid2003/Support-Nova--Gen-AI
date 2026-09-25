"""Knowledge base: documents, versions (Active/Previous/Superseded/Draft), sections and traceable chunks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from supportnova.database.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    doc_type: Mapped[str] = mapped_column(String(20), index=True)  # policy|rules|sop|guideline|faq|template
    owner_department: Mapped[str | None] = mapped_column(String(32), nullable=True)
    topics: Mapped[list[Any]] = mapped_column(default=list)
    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document", order_by="DocumentVersion.id",
                                                           cascade="all, delete-orphan")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_versions_doc_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)  # Active | Previous | Superseded | Draft
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    file_name: Mapped[str] = mapped_column(String(200))
    file_format: Mapped[str] = mapped_column(String(8))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(String(400))
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    supersedes: Mapped[str | None] = mapped_column(String(16), nullable=True)
    security_findings: Mapped[list[Any]] = mapped_column(default=list)
    facts: Mapped[list[Any]] = mapped_column(default=list)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="versions")
    sections: Mapped[list[DocumentSection]] = relationship(back_populates="version", cascade="all, delete-orphan",
                                                           order_by="DocumentSection.order_index")
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="version", cascade="all, delete-orphan",
                                                       order_by="DocumentChunk.order_index")


class DocumentSection(Base):
    """Policy / SOP section with preserved numbering, heading and page span (SRS Steps 5-6)."""

    __tablename__ = "document_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(32))
    heading: Mapped[str] = mapped_column(String(300))
    level: Mapped[int] = mapped_column(Integer, default=1)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[DocumentVersion] = relationship(back_populates="sections")


class DocumentChunk(Base):
    """Retrieval unit. chunk_uid = <DOC_ID>@<version>#<section>-c<n> keeps every chunk traceable."""

    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_uid: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(32))
    heading: Mapped[str] = mapped_column(String(300))
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(64), default="")
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
