"""Platform-wide settings (superadmin): site branding + global switchboard.

Stored as a stable set of key→JSON rows so the landing page, splash and
sign-in flows can render a branded name/tagline while a single switchboard
controls e.g. whether self-serve registration is open.
"""
from ..extensions import db
from .common import TimestampsMixin

SITE_KEY = "site"

DEFAULT_SETTINGS = {
    "site_name": "Verifo",
    "tagline": "Confirm documents are genuine — in seconds, not weeks.",
    "support_email": "support@demo.edu",
    "footer_text": "Verifo · Document verification that ships",
    "registration_open": True,
    "demo_mode": False,
    "announcement": "",
}


def default_platform_settings() -> dict:
    return dict(DEFAULT_SETTINGS)


class PlatformSetting(db.Model, TimestampsMixin):
    """Singleton-ish key/value store with JSON values."""

    __tablename__ = "platform_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.JSON, nullable=False)

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value}


def get_platform_settings() -> dict:
    """Merge stored values over defaults; safe to call outside a DB context."""
    from ..extensions import db

    row = None
    try:
        row = db.session.get(PlatformSetting, SITE_KEY)
    except Exception:  # noqa: BLE001 - pre-init/boot when tables may not exist
        pass
    merged = default_platform_settings()
    if row and isinstance(row.value, dict):
        merged.update(row.value)
    return merged


def save_platform_settings(values: dict) -> dict:
    """Persist (overwriting) the site settings block and return the merged map."""
    merged = default_platform_settings()
    merged.update(values or {})
    row = db.session.get(PlatformSetting, SITE_KEY)
    if row is None:
        db.session.add(PlatformSetting(key=SITE_KEY, value=merged))
    else:
        row.value = merged
    return merged


def ensure_platform_settings() -> dict:
    """Create the settings row with defaults if missing; return merged map."""
    if db.session.get(PlatformSetting, SITE_KEY) is None:
        db.session.add(PlatformSetting(key=SITE_KEY, value=default_platform_settings()))
        db.session.flush()
    return get_platform_settings()