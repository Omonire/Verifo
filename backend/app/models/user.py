"""User model. Request-scoped tenant helpers live in app/auth/context.py."""
import re
from datetime import datetime, timezone

from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .common import PkUuidMixin, StatusCode, TimestampsMixin, model_enum
from .organization import Membership

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class User(db.Model, PkUuidMixin, TimestampsMixin):
    __tablename__ = "users"

    email = db.Column(db.String(320), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    status = db.Column(model_enum(StatusCode), default=StatusCode.ACTIVE, nullable=False)
    is_superadmin = db.Column(db.Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    memberships = db.relationship(
        "Membership",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @validates("email")
    def _validate_email(self, key, value):
        value = (value or "").strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("Invalid email address.")
        return value

    def set_password(self, raw: str) -> None:
        if not raw or len(raw) < 8:
            raise ValueError("Password must be at least 8 characters.")
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw or "")

    def touch_login(self) -> None:
        self.last_login_at = datetime.now(timezone.utc)

    def active_memberships(self) -> list[Membership]:
        return [
            m
            for m in self.memberships
            if m.status == StatusCode.ACTIVE and m.organization.status == StatusCode.ACTIVE
        ]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "status": self.status.value if self.status else None,
            "is_superadmin": bool(self.is_superadmin),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }