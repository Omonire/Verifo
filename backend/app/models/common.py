"""Shared model primitives and enumerations."""
import enum
import uuid
from datetime import datetime, timezone

from ..extensions import db


def uuid_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoleCode(str, enum.Enum):
    SUBMITTER = "SUBMITTER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"
    SUPERADMIN = "SUPERADMIN"

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


class StatusCode(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


def model_enum(enum_cls):
    """Return a DB Enum column type portable across SQLite/Postgres."""
    return db.Enum(enum_cls, native_enum=False, values_callable=lambda e: [m.value for m in e])


class TimestampsMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    updated_at = db.Column(
        db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PkUuidMixin:
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)