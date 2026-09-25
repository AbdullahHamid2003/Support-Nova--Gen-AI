"""Users, roles (RBAC), simulated customers, departments, taxonomy and products."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from supportnova.database.base import Base, TimestampMixin


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[list[Any]] = mapped_column(default=list)


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subcategories: Mapped[list[Subcategory]] = relationship(back_populates="category", order_by="Subcategory.code")


class Subcategory(Base, TimestampMixin):
    __tablename__ = "subcategories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[Category] = relationship(back_populates="subcategories")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    line: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[str] = mapped_column(String(32), default="device")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    warranty_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hazard_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aliases: Mapped[list[Any]] = mapped_column(default=list)


class Customer(Base, TimestampMixin):
    """Simulated customer profile (fictional). May be linked to a login user."""

    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_ref: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_type: Mapped[str] = mapped_column(String(32), default="individual")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(200))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped[Role] = relationship(lazy="joined")
    department: Mapped[Department | None] = relationship(lazy="joined")
    customer: Mapped[Customer | None] = relationship(lazy="joined")

    @property
    def role_code(self) -> str:
        return self.role.code if self.role else ""

    @property
    def permissions(self) -> set[str]:
        return set(self.role.permissions or []) if self.role else set()
