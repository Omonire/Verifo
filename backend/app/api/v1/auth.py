"""Authentication endpoints: register, login, me, switch-org."""
import re

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity

from ...auth import issue_app_token, issue_superadmin_token, require_auth, require_org
from ...extensions import db
from ...models.common import RoleCode, StatusCode
from ...models.organization import Membership, Organization
from ...models.user import User
from ...repositories.index import OrganizationRepository, UserRepository
from ...schemas import LoginSchema, RegisterSchema
from ...services.audit import AuditService
from ...utils.response import api_error, api_ok

auth_bp = Blueprint("auth", __name__)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "org")[:60]


def _issue_token(user: User, membership: Membership) -> str:
    role = membership.role.value if membership.role else RoleCode.SUBMITTER.value
    return issue_app_token(user.id, membership.organization_id, role)


def _set_session_cookie(payload: dict, token: str):
    from flask import jsonify
    from flask_jwt_extended import set_access_cookies

    body = {"success": True}
    body.update(payload)
    resp = jsonify(body)
    set_access_cookies(resp, token)
    return resp


def _default_membership(memberships):
    """Pick the session organization deterministically when a user belongs to several.

    Prefers orgs that behave like the built-in demo, then any org the user
    administers, so single- and multi-tenant logins both yield a usable token.
    """
    if not memberships:
        return None
    for pref in (
        lambda m: getattr(m.organization, "slug", None) == "demo",
        lambda m: m.role in (RoleCode.ADMIN, None),
    ):
        chosen = next((m for m in memberships if pref(m)), None)
        if chosen is not None:
            return chosen
    return memberships[0]


@auth_bp.post("/register")
def register():
    from ...models.platform import get_platform_settings

    if not get_platform_settings().get("registration_open", True):
        return api_error(
            "REGISTRATION_CLOSED",
            "Self-serve registration is currently closed. Contact the platform administrator.",
            status=403,
        )
    data = request.get_json(silent=True) or {}
    # Frontend sends org_name/org_slug; API contract normalizes to long names.
    normalized = dict(data)
    normalized.setdefault("organization_name", data.get("org_name") or "")
    normalized.setdefault("organization_slug", data.get("org_slug") or "")
    clean = RegisterSchema(normalized).validate()

    org_repo = OrganizationRepository()
    user_repo = UserRepository()

    slug = clean["organization_slug"] or _slugify(clean["organization_name"])
    if org_repo.get_by_slug(slug):
        return api_error("SLUG_TAKEN", "That organization slug is already taken.")
    if user_repo.get_by_email(clean["email"]):
        return api_error("EMAIL_TAKEN", "An account with this email already exists.")

    org = Organization(
        name=clean["organization_name"],
        slug=slug,
        industry=(data.get("industry") or "").strip() or None,
    )
    user = user_repo.create_user(clean["email"], clean["full_name"], clean["password"])
    db.session.add(org)
    db.session.flush()

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=RoleCode.ADMIN,
        status=StatusCode.ACTIVE,
    )
    db.session.add(membership)
    AuditService.commit(
        organization_id=org.id,
        action="ORG_CREATED",
        entity_type="Organization",
        entity_id=org.id,
        summary=f"Organization '{org.name}' created with admin {user.email}.",
        after={"name": org.name, "slug": org.slug, "industry": org.industry},
        actor_user_id=user.id,
        actor_name=user.full_name,
    )
    db.session.commit()

    token = _issue_token(user, membership)
    return _set_session_cookie(
        {
            "token": token,
            "user": user.to_dict(),
            "membership": membership.to_dict(),
        },
        token,
    ), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    clean = LoginSchema(data).validate()

    user = User.query.filter_by(email=clean["email"].lower()).first()
    if not user or not user.check_password(clean["password"]):
        AuditService.commit(
            organization_id=None,
            action="AUTH_LOGIN_FAILURE",
            entity_type="User",
            summary=f"Login failed for {clean['email']}.",
        )
        db.session.commit()
        return api_error("INVALID_CREDENTIALS", "Invalid email or password.", status=401)
    if user.status != StatusCode.ACTIVE:
        return api_error("ACCOUNT_SUSPENDED", "This account is suspended.", status=403)

    memberships = user.active_memberships()
    if not memberships:
        if user.is_superadmin:
            user.touch_login()
            AuditService.commit(
                organization_id=None,
                action="USER_LOGIN",
                entity_type="User",
                entity_id=user.id,
                summary=f"{user.email} signed in (platform superadmin).",
                actor_user_id=user.id,
                actor_name=user.full_name,
            )
            db.session.commit()
            token = issue_superadmin_token(user.id)
            return _set_session_cookie(
                {
                    "token": token,
                    "user": user.to_dict(),
                    "role": RoleCode.SUPERADMIN.value,
                },
                token,
            ), 200
        return api_error(
            "NO_MEMBERSHIP", "This account has no active organization membership.", status=403
        )

    active = _default_membership(memberships)
    user.touch_login()
    AuditService.commit(
        organization_id=active.organization_id if active else None,
        action="USER_LOGIN",
        entity_type="User",
        entity_id=user.id,
        summary=f"{user.email} signed in.",
        actor_user_id=user.id,
        actor_name=user.full_name,
    )
    db.session.commit()

    response = {
        "user": user.to_dict(),
        "memberships": [m.to_dict() for m in memberships],
    }
    if active:
        response["token"] = _issue_token(user, active)
        response["active_membership"] = active.to_dict()
        return _set_session_cookie(response, response["token"]), 200
    return api_ok(response), 200


@auth_bp.get("/me")
@require_auth
def me():
    from flask_jwt_extended import get_jwt

    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user:
        return api_error("NOT_FOUND", "User not found.", status=404)
    user_detail = user.to_dict()
    try:
        org_id = require_org()
        org = Organization.query.get(org_id)
        if not org:
            return api_error("NOT_FOUND", "Organization not found.", status=404)
        user_detail["organization"] = org.to_dict()
        user_detail["role"] = get_jwt().get("role")
    except PermissionError:
        if not user.is_superadmin:
            return api_error("NO_MEMBERSHIP", "No workplace selected.", status=403)
        user_detail["organization"] = None
        user_detail["role"] = RoleCode.SUPERADMIN.value
    return api_ok({"user": user_detail}), 200


@auth_bp.post("/demologin")
def demologin():
    """Development-only: issue an admin token with zero credentials.

    Powers the out-of-the-box demo. Guards on DEMO_AUTH_ENABLED, which is
    never true in Production or Testing configs.
    """
    if not current_app.config.get("DEMO_AUTH_ENABLED"):
        return api_error("FORBIDDEN", "Demo auth is disabled in this environment.", status=403)

    org_repo = OrganizationRepository()
    org = org_repo.get_by_slug("demo")
    if org is None:
        org = Organization(
            name="Demo University of Technology",
            slug="demo",
            industry="University",
        )
        db.session.add(org)
        db.session.flush()

    user_repo = UserRepository()
    user = user_repo.get_by_email("admin@demo.edu")
    if user is None:
        user = user_repo.create_user("admin@demo.edu", "Demo Administrator", "verifo-demo-admin")
        db.session.flush()

    membership = next(
        (m for m in user.active_memberships() if m.organization_id == org.id), None
    )
    if membership is None:
        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=RoleCode.ADMIN,
            status=StatusCode.ACTIVE,
        )
        db.session.add(membership)

    AuditService.commit(
        organization_id=org.id,
        action="DEMO_SESSION",
        entity_type="Organization",
        entity_id=org.id,
        summary=f"Demo session for {user.email}.",
        actor_user_id=user.id,
        actor_name=user.full_name,
    )
    db.session.commit()
    user_detail = user.to_dict()
    user_detail["organization"] = org.to_dict()
    user_detail["role"] = membership.role.value if membership.role else None
    token = _issue_token(user, membership)
    return _set_session_cookie(
        {
            "token": token,
            "user": user_detail,
            "membership": membership.to_dict(),
            "demo": True,
        },
        token,
    ), 200


@auth_bp.post("/switch-org")
@require_auth
def switch_org():
    uid = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    org_id = data.get("organization_id")
    user = User.query.get(uid)
    if not user:
        return api_error("NOT_FOUND", "User not found.", status=404)
    membership = next(
        (m for m in user.active_memberships() if m.organization_id == org_id), None
    )
    if not membership:
        return api_error("FORBIDDEN", "You are not a member of that organization.", status=403)
    token = _issue_token(user, membership)
    return _set_session_cookie({"token": token, "membership": membership.to_dict()}, token), 200