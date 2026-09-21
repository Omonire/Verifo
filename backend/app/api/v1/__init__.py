from flask import Blueprint

from .admin import admin_bp
from .apikeys import apikeys_bp
from .auth import auth_bp
from .documenttypes import documenttypes_bp
from .demo import demo_bp
from .downloads import downloads_bp
from .external import external_bp
from .health import health_bp
from .jobs import jobs_bp
from .org import org_bp
from .references import references_bp
from .superadmin import superadmin_bp
from .users import users_bp
from .verifications import verifications_bp

api_v1_bp = Blueprint("api_v1", __name__)
api_v1_bp.register_blueprint(health_bp, url_prefix="/health")
api_v1_bp.register_blueprint(auth_bp, url_prefix="/auth")
api_v1_bp.register_blueprint(org_bp, url_prefix="/org")
api_v1_bp.register_blueprint(users_bp, url_prefix="/users")
api_v1_bp.register_blueprint(downloads_bp, url_prefix="/downloads")
api_v1_bp.register_blueprint(documenttypes_bp, url_prefix="/document-types")
api_v1_bp.register_blueprint(demo_bp, url_prefix="/demo")
api_v1_bp.register_blueprint(references_bp, url_prefix="/references")
api_v1_bp.register_blueprint(superadmin_bp, url_prefix="/superadmin")
api_v1_bp.register_blueprint(verifications_bp, url_prefix="/verifications")
api_v1_bp.register_blueprint(jobs_bp, url_prefix="/screening/jobs")
api_v1_bp.register_blueprint(admin_bp, url_prefix="/admin")
api_v1_bp.register_blueprint(apikeys_bp, url_prefix="/api-keys")
api_v1_bp.register_blueprint(external_bp, url_prefix="/api")

__all__ = ["api_v1_bp"]