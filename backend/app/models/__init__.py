"""Model package: import every model so metadata is complete for migrations."""
from .organization import Membership, Organization
from .platform import PlatformSetting
from .user import User
from .audit import AuditLog
from .apikey import APIKey
from .domain import (
    DocumentType,
    QueueTask,
    ReferenceDocument,
    ScreeningItem,
    ScreeningJob,
    Verification,
)

__all__ = [
    "APIKey",
    "AuditLog",
    "DocumentType",
    "Membership",
    "Organization",
    "PlatformSetting",
    "QueueTask",
    "ReferenceDocument",
    "ScreeningItem",
    "ScreeningJob",
    "User",
    "Verification",
]