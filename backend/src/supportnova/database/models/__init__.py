"""All ORM models (imported here so Alembic autogenerate and create_all see every table)."""

from .complaints import Complaint, ComplaintAttachment, ComplaintHistory, Order, SlaRecord
from .identity import Category, Customer, Department, Product, Role, Subcategory, User
from .intelligence import (
    AIRun,
    Analysis,
    PolicyReference,
    Prompt,
    PromptVersion,
    RuleRecord,
    SystemSetting,
    ValidationCheck,
    ValidationResult,
)
from .knowledge import Document, DocumentChunk, DocumentSection, DocumentVersion
from .workflow import (
    AuditLog,
    CustomerResponse,
    Escalation,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    FollowUp,
    Resolution,
    Review,
    ReviewAction,
)

__all__ = [
    "AIRun", "Analysis", "AuditLog", "Category", "Complaint", "ComplaintAttachment", "ComplaintHistory", "Customer",
    "CustomerResponse", "Department", "Document", "DocumentChunk", "DocumentSection", "DocumentVersion", "Escalation",
    "EvaluationCase", "EvaluationResult", "EvaluationRun", "FollowUp", "Order", "PolicyReference", "Product", "Prompt",
    "PromptVersion", "Resolution", "Review", "ReviewAction", "Role", "RuleRecord", "SlaRecord", "Subcategory",
    "SystemSetting", "User", "ValidationCheck", "ValidationResult",
]
