"""Авторизация панели: страница входа + Telegram WebApp login + logout."""
from flask import render_template, request, jsonify

import config
import panel_auth
import web_helpers
from web_blueprints import auth_bp


@auth_bp.route('/auth')
def auth_page():
    return render_template('auth.html', config=config)


@auth_bp.route('/api/auth/tg', methods=['POST'])
def api_auth_tg():
    """Вход через Telegram WebApp: принимаем initData, выдаём сессионную cookie."""
    data = request.json or {}
    init_data = data.get('initData', '')
    user = panel_auth.validate_tg_init_data(init_data, config.TELEGRAM_TOKEN)
    if not user or not web_helpers.is_admin(user.get('id')):
        return jsonify({'status': 'error', 'error': 'Access denied'}), 403
    token = panel_auth.make_session_token(user['id'], config.TELEGRAM_TOKEN)
    resp = jsonify({'status': 'success', 'user_id': user['id'], 'username': user.get('username', '')})
    resp.set_cookie(web_helpers.SESSION_COOKIE, token, max_age=7 * 24 * 3600, httponly=True, samesite='Lax')
    return resp


@auth_bp.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """Вход по Basic-авторизации (логин/пароль), выдаёт сессионную cookie."""
    if not config.PANEL_PASSWORD:
        return jsonify({'status': 'error', 'error': 'Basic auth not configured'}), 403
    data = request.json or {}
    username = data.get('username', request.authorization.username if request.authorization else '')
    password = data.get('password', request.authorization.password if request.authorization else '')
    if username == config.PANEL_USER and password == config.PANEL_PASSWORD:
        admin_id = config.ADMIN_IDS[0] if config.ADMIN_IDS else 0
        token = panel_auth.make_session_token(admin_id, config.TELEGRAM_TOKEN)
        resp = jsonify({'status': 'success', 'user_id': admin_id})
        resp.set_cookie(web_helpers.SESSION_COOKIE, token, max_age=7 * 24 * 3600, httponly=True, samesite='Lax')
        return resp
    return jsonify({'status': 'error', 'error': 'Invalid credentials'}), 403


@auth_bp.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    resp = jsonify({'status': 'success'})
    resp.delete_cookie(web_helpers.SESSION_COOKIE)
    return resp


@auth_bp.route('/api/auth/me', methods=['GET'])
def api_auth_me():
    uid = web_helpers.check_session(request)
    if uid:
        return jsonify({'status': 'success', 'authenticated': True, 'user_id': uid})
    if web_helpers.check_basic_auth(request):
        return jsonify({'status': 'success', 'authenticated': True, 'user_id': None})
    return jsonify({'status': 'success', 'authenticated': False})
