"""Token issuance/decoding helpers (app, download, and API scopes)."""
from datetime import timedelta

from flask import current_app
from flask_jwt_extended import create_access_token, decode_token

from .context import current_role

TOKEN_TYPES = ("app", "download")


def issue_app_token(user_id: str, organization_id: str, role: str) -> str:
    """Issue an app-scoped token carrying the active tenant context."""
    claims = {"role": role, "token_type": "app"}
    if organization_id:
        claims["org"] = organization_id
    return create_access_token(
        identity=str(user_id),
        additional_claims=claims,
    )


def issue_superadmin_token(user_id: str) -> str:
    """Issue a platform-scoped token (no org claim) for a superadmin session."""
    return issue_app_token(user_id, None, "SUPERADMIN")


def issue_download_token(organization_id: str, storage_path: str) -> str:
    """Short-lived token granting read access to exactly one stored file."""
    return create_access_token(
        identity="download",
        additional_claims={
            "scope": "download",
            "org": organization_id,
            "path": storage_path,
        },
        expires_delta=current_app.config["DOWNLOAD_TOKEN_TTL"],
    )


def decode_app_token(token: str) -> dict:
    claims = decode_token(token)
    if claims.get("token_type") != "app":
        raise PermissionError("Token is not an application token.")
    return claims


def decode_download_token(token: str) -> dict:
    claims = decode_token(token)
    if claims.get("scope") != "download":
        raise PermissionError("Token is not a download token.")
    return {"org_id": claims["org"], "path": claims["path"]}


def current_role_value() -> str | None:
    return current_role()