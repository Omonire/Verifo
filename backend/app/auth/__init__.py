"""Authentication and authorization package for Verifo."""
from .context import (
    current_role,
    current_tenant,
    current_user_id,
    is_authenticated,
    require_org,
)
from .decorators import (
    AuthenticationRequiredError,
    AuthorizationError,
    require_auth,
    roles_required,
)
from .tokens import (
    decode_app_token,
    decode_download_token,
    issue_app_token,
    issue_download_token,
    issue_superadmin_token,
)

__all__ = [
    "AuthenticationRequiredError",
    "AuthorizationError",
    "current_role",
    "current_tenant",
    "current_user_id",
    "decode_app_token",
    "decode_download_token",
    "is_authenticated",
    "issue_app_token",
    "issue_download_token",
    "issue_superadmin_token",
    "require_auth",
    "require_org",
    "roles_required",
]