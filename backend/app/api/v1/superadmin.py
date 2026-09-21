"""Superadmin area: platform settings, switchboard, organizations, users.

Auth model: callers present any valid app token to `/bootstrap`, which—after
verifying the account is a superadmin in the database—swaps it for a
platform-scoped token (no `org` claim). Every other route here requires a
`SUPERADMIN` platform token via `roles_required`.
"""
import re

from flask import Blueprint, request

from ...auth import current_user_id, issue_superadmin_token, require_auth, roles_required
from ...extensions import db
from ...models.common import RoleCode, StatusCode
from ...models.organization import Membership, Organization
from ...models.platform import get_platform_settings, save_platform_settings
from ...models.user import User
from ...services.audit import AuditService
from ...utils.response import api_error, api_ok

superadmin_bp = Blueprint("superadmin", __name__)

_ALLOWED_SETTING_KEYS = {
    "site_name",
    "tagline",
    "support_email",
    "footer_text",
    "registration_open",
    "demo_mode",
    "announcement",
}


def _is_superadmin_user(user_id: str) -> bool:
    user = User.query.get(user_id)
    return bool(user and user.is_superadmin)


@superadmin_bp.get("/bootstrap")
@require_auth
def bootstrap():
    """Swap the caller's token for a platform-scoped superadmin token."""
    uid = current_user_id()
    if not _is_superadmin_user(uid):
        return api_error("FORBIDDEN", "This account is not a platform superadmin.", status=403)
    token = issue_superadmin_token(uid)
    return api_ok({"token": token, "role": RoleCode.SUPERADMIN.value}), 200


@superadmin_bp.get("/settings")
@roles_required(RoleCode.SUPERADMIN.value)
def get_settings():
    return api_ok({"settings": get_platform_settings()}), 200


@superadmin_bp.put("/settings")
@roles_required(RoleCode.SUPERADMIN.value)
def update_settings():
    data = request.get_json(silent=True) or {}
    unknown = set(data) - _ALLOWED_SETTING_KEYS
    if unknown:
        return api_error("INVALID_INPUT",
                         f"Unknown setting(s): {', '.join(sorted(unknown))}.")
    cleaned = {}
    for key in _ALLOWED_SETTING_KEYS:
        if key not in data:
            continue
        value = data[key]
        if key in ("registration_open", "demo_mode"):
            if not isinstance(value, bool):
                return api_error("INVALID_INPUT", f"{key} must be a boolean.")
            cleaned[key] = value
        else:
            cleaned[key] = str(value).strip()
    merged = save_platform_settings(cleaned)
    AuditService.commit(
        organization_id=None, action="PLATFORM_SETTINGS_UPDATED",
        entity_type="PlatformSetting", summary="Platform site/branding settings updated.",
        actor_user_id=current_user_id(), after=cleaned)
    db.session.commit()
    return api_ok({"settings": merged}), 200


@superadmin_bp.get("/organizations")
@roles_required(RoleCode.SUPERADMIN.value)
def list_organizations():
    q = request.args.get("q", "").strip().lower()
    rows = Organization.query.all()
    items = []
    for org in rows:
        if q and q not in org.name.lower() and q not in org.slug.lower():
            continue
        member_count = Membership.query.filter_by(
            organization_id=org.id, status=StatusCode.ACTIVE).count()
        items.append({
            **org.to_dict(),
            "member_count": member_count,
        })
    return api_ok({"organizations": items}), 200


@superadmin_bp.post("/organizations")
@roles_required(RoleCode.SUPERADMIN.value)
def create_organization():
    from ...repositories.index import UserRepository

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    slug = (data.get("slug") or "").strip().lower()
    if not name or not slug:
        return api_error("INVALID_INPUT", "name and slug are required.")
    if Organization.query.filter_by(slug=slug).first():
        return api_error("EXISTS", f"Organization slug '{slug}' is already taken.")

    org = Organization(name=name, slug=slug,
                       industry=(data.get("industry") or "").strip() or None)
    db.session.add(org)
    db.session.flush()

    extra = {}
    admin_email = (data.get("admin_email") or "").strip().lower()
    if admin_email:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", admin_email):
            return api_error("INVALID_INPUT", "admin_email is not a valid email.")
        password = data.get("admin_password") or ""
        if len(password) < 8:
            return api_error("INVALID_INPUT", "admin_password must be at least 8 characters.")
        repo = UserRepository()
        user = repo.get_by_email(admin_email)
        if user is None:
            user = repo.create_user(admin_email, (data.get("admin_name") or "").strip() or "Administrator", password)
            db.session.flush()
        Membership.query.filter_by(user_id=user.id, organization_id=org.id).delete()
        membership = Membership(user_id=user.id, organization_id=org.id,
                                role=RoleCode.ADMIN, status=StatusCode.ACTIVE)
        db.session.add(membership)
        db.session.flush()
        extra["admin"] = {"id": user.id, "email": user.email, "full_name": user.full_name}

    AuditService.commit(
        organization_id=org.id, action="ORG_CREATED",
        entity_type="Organization", entity_id=org.id,
        summary=f"Organization '{name}' created by platform superadmin.",
        actor_user_id=current_user_id(), after={"name": name, "slug": slug})
    db.session.commit()
    return api_ok({"organization": org.to_dict(), **extra}), 201


@superadmin_bp.post("/organizations/<org_id>/status")
@roles_required(RoleCode.SUPERADMIN.value)
def set_org_status(org_id):
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "").upper()
    if status not in ("ACTIVE", "SUSPENDED"):
        return api_error("INVALID_INPUT", "status must be ACTIVE or SUSPENDED.")
    org = Organization.query.get(org_id)
    if not org:
        return api_error("NOT_FOUND", "Organization not found.", status=404)
    old = org.status.value if org.status else None
    org.status = StatusCode(status)
    AuditService.commit(
        organization_id=org.id, action="ORG_STATUS_CHANGED",
        entity_type="Organization", entity_id=org.id,
        summary=f"Organization set to {status}.",
        actor_user_id=current_user_id(), before={"status": old}, after={"status": status})
    db.session.commit()
    return api_ok({"organization": org.to_dict()}), 200


@superadmin_bp.get("/users")
@roles_required(RoleCode.SUPERADMIN.value)
def list_users():
    q = request.args.get("q", "").strip().lower()
    rows = User.query.order_by(User.created_at.desc()).limit(500).all()
    items = []
    for user in rows:
        if q and (q not in user.email.lower()
                  and q not in (user.full_name or "").lower()):
            continue
        memberships = []
        for m in user.memberships:
            org = m.organization
            if org:
                memberships.append({
                    "organization_id": org.id,
                    "organization_name": org.name,
                    "organization_status": org.status.value if org.status else None,
                    "role": m.role.value if m.role else None,
                    "status": m.status.value if m.status else None,
                })
        items.append({
            **user.to_dict(),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "memberships": memberships,
        })
    return api_ok({"users": items}), 200


@superadmin_bp.post("/users/<user_id>/status")
@roles_required(RoleCode.SUPERADMIN.value)
def set_user_status(user_id):
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "").upper()
    if status not in ("ACTIVE", "SUSPENDED"):
        return api_error("INVALID_INPUT", "status must be ACTIVE or SUSPENDED.")
    user = User.query.get(user_id)
    if not user:
        return api_error("NOT_FOUND", "User not found.", status=404)
    user.status = StatusCode(status)
    if status == "SUSPENDED" and user.is_superadmin:
        return api_error("INVALID_INPUT", "Suspend a superadmin by removing the flag first.")
    old = user.status.value if user.status else None
    AuditService.commit(
        organization_id=None, action="USER_STATUS_CHANGED",
        entity_type="User", entity_id=user.id,
        summary=f"User {user.email} set to {status}.",
        actor_user_id=current_user_id(), before={"status": old}, after={"status": status})
    db.session.commit()
    return api_ok({"user": user.to_dict()}), 200


@superadmin_bp.post("/users/<user_id>/superadmin")
@roles_required(RoleCode.SUPERADMIN.value)
def toggle_superadmin(user_id):
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("is_superadmin"), bool):
        return api_error("INVALID_INPUT", "is_superadmin must be a boolean.")
    user = User.query.get(user_id)
    if not user:
        return api_error("NOT_FOUND", "User not found.", status=404)
    if user.id == current_user_id() and not body["is_superadmin"]:
        return api_error("INVALID_INPUT", "You cannot remove your own superadmin access.")
    if body["is_superadmin"] and user.status != StatusCode.ACTIVE:
        return api_error("INVALID_INPUT", "Activate the account before promoting it.")
    user.is_superadmin = body["is_superadmin"]
    AuditService.commit(
        organization_id=None, action="SUPERADMIN_CHANGED",
        entity_type="User", entity_id=user.id,
        summary=f"{user.email} superadmin = {body['is_superadmin']}.",
        actor_user_id=current_user_id(), after={"is_superadmin": user.is_superadmin})
    db.session.commit()
    return api_ok({"user": user.to_dict()}), 200