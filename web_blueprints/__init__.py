"""Blueprints веб-панели: auth, main (дашборд + legacy API), platform (/api/platform/*)."""
from flask import Blueprint

auth_bp = Blueprint('auth_bp', __name__)
main_bp = Blueprint('main_bp', __name__)
platform_bp = Blueprint('platform_bp', __name__)

import web_blueprints.auth  # noqa: E402,F401
import web_blueprints.main  # noqa: E402,F401
import web_blueprints.platform  # noqa: E402,F401
