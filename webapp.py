from flask import Flask, request, jsonify, redirect

import config

from web_blueprints import auth_bp, main_bp, platform_bp

app = Flask(__name__)

_AUTH_EXEMPT = {'/auth', '/login'}
_AUTH_EXEMPT_PREFIXES = ('/static/', '/api/auth/', '/logo.png', '/favicon.ico')


@app.before_request
def _require_auth():
    # Авторизация отключена полностью — только для тестов/локальной разработки.
    if not getattr(config, 'PANEL_AUTH_REQUIRED', True):
        return None
    if request.path in _AUTH_EXEMPT or request.path.startswith(_AUTH_EXEMPT_PREFIXES):
        return None
    import web_helpers
    if web_helpers.check_session(request):
        return None
    if web_helpers.check_basic_auth(request):
        return None
    # HTML-страницы → редирект на страницу входа; API → 401 JSON.
    if request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'error': 'Unauthorized'}), 401
    return redirect('/auth?next=' + request.path)


app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)
app.register_blueprint(platform_bp)


def run_server():
    import os
    port = int(os.environ.get("PORT", 8080))
    try:
        from waitress import serve
        print(f"🚀 Web Dashboard (waitress) на порту {port}")
        serve(app, host='0.0.0.0', port=port, threads=8)
    except ImportError:
        print("⚠️ waitress не установлен, использую Flask dev server")
        app.run(host='0.0.0.0', port=port)
