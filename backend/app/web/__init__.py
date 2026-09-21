"""Web blueprint: server-rendered HTML pages (Flask + Jinja2 + vanilla JS/CSS)."""
from datetime import datetime
from functools import wraps

from flask import Blueprint, redirect, render_template, url_for
from flask_jwt_extended import verify_jwt_in_request

from ..auth import current_role, current_user_id
from ..models.common import RoleCode

web_bp = Blueprint("web", __name__)


def page_access(*roles: str):
    """Gate a workspace page by JWT role; redirect non-members to safety."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                verify_jwt_in_request()
            except Exception:
                return redirect(url_for("web.signin"))
            if current_role() not in roles:
                return redirect(url_for("web.dashboard"))
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@web_bp.app_context_processor
def inject_globals():
    from ..models.platform import get_platform_settings

    return {
        "current_year": lambda: datetime.now().year,
        "site": get_platform_settings(),
    }


def page(template, **kwargs):
    return render_template(template, **kwargs)


# --- Marketing / public pages ---


@web_bp.get("/")
def landing():
    return page("landing.html")


# --- Identity (VERIX-style) auth pages ---


@web_bp.get("/signin")
def signin():
    return page("signin.html", active="signin")


@web_bp.get("/login")
def login_alias():
    return page("signin.html", active="signin")


@web_bp.get("/request-access")
def request_access():
    from ..models.platform import get_platform_settings

    return page(
        "request_access.html",
        active="request",
        registration_open=get_platform_settings().get("registration_open", True),
    )


@web_bp.get("/register")
def register_alias():
    return page("request_access.html", active="request")


@web_bp.get("/mfa")
def mfa():
    return page("mfa.html", active="mfa")


@web_bp.get("/reset")
def reset():
    return page("reset.html", active="reset")


# --- Legal / policy pages ---


@web_bp.get("/policy")
def privacy_policy():
    return page("privacy.html", section="policy")


@web_bp.get("/terms")
def terms():
    return page("terms.html", section="terms")


# --- Workspace pages (data loaded client-side via the /api/v1 surface) ---


@web_bp.get("/dashboard")
@page_access(RoleCode.ADMIN.value, RoleCode.OPERATOR.value, RoleCode.SUBMITTER.value)
def dashboard():
    return page("dashboard.html")


@web_bp.get("/verify")
@page_access(RoleCode.ADMIN.value, RoleCode.OPERATOR.value, RoleCode.SUBMITTER.value)
def verify():
    return page("verify.html")


@web_bp.get("/my-results")
@page_access(RoleCode.ADMIN.value, RoleCode.OPERATOR.value, RoleCode.SUBMITTER.value)
def my_results():
    return page("my_results.html")


@web_bp.get("/screening")
@page_access(RoleCode.ADMIN.value, RoleCode.OPERATOR.value)
def screening():
    return page("screening.html")


@web_bp.get("/references")
@page_access(RoleCode.ADMIN.value, RoleCode.OPERATOR.value)
def references():
    return page("references.html")


@web_bp.get("/settings")
@page_access(RoleCode.ADMIN.value, RoleCode.OPERATOR.value)
def settings():
    return page("settings.html")


@web_bp.get("/superadmin")
def superadmin():
    """Platform console. Grant is DB-backed (`User.is_superadmin`), so a
    workspace ADMIN token still works here — the page swaps to a platform
    token via /api/v1/superadmin/bootstrap."""
    try:
        verify_jwt_in_request()
    except Exception:
        return redirect(url_for("web.signin"))
    from ..models.user import User

    user = User.query.get(current_user_id())
    if not user or not user.is_superadmin:
        return redirect(url_for("web.dashboard"))
    return page("superadmin.html")