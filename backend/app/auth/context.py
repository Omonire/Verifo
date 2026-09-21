"""Request-scoped tenant/auth context derived from validated JWT claims.

The active organization and role ALWAYS come from the token, never from
client-supplied parameters. Routes call current_org_id()/current_role() and
data access layers enforce the tenant scope server-side.
"""
from flask_jwt_extended import get_jwt, get_jwt_identity


def is_authenticated() -> bool:
    return bool(get_jwt())


def current_user_id() -> str | None:
    return get_jwt_identity()


def current_tenant() -> dict | None:
    """Return {org_id, role} from the current token, or None."""
    claims = get_jwt()
    return {"org_id": claims["org"], "role": claims["role"]} if claims.get("org") else None


def require_org() -> str:
    tenant = current_tenant()
    if not tenant:
        raise PermissionError("Organization context missing from token.")
    return tenant["org_id"]


def current_role() -> str | None:
    claims = get_jwt()
    if not claims:
        return None
    if claims.get("org"):
        return claims.get("role")
    # Platform (superadmin) tokens carry a role but no org context.
    from ..models.common import RoleCode

    return claims.get("role") if claims.get("role") == RoleCode.SUPERADMIN.value else None