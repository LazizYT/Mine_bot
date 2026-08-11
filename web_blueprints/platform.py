"""Content Distribution Platform API (/api/platform/*) + страница /platform."""
import time

from flask import render_template, request, jsonify

import config
import database
import content_storage
import channel_manager
import scheduler_engine
from bot_instance import bot
from web_blueprints import platform_bp


@platform_bp.route('/api/platform/posts', methods=['GET'])
def api_platform_posts():
    status = request.args.get('status')
    category = request.args.get('category')
    language = request.args.get('language')
    source = request.args.get('source')
    tag = request.args.get('tag')
    q = request.args.get('q')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    data = content_storage.list_posts(
        status=status, category=category, language=language, source=source,
        tag=tag, search=q, page=page, per_page=per_page)
    cols = ['id', 'title', 'text', 'category', 'language', 'source', 'status', 'priority',
            'usage_count', 'times_published', 'last_used_at', 'tags', 'media', 'created_at']
    items = [dict(zip(cols, row)) for row in data['items']]
    return jsonify({'status': 'success', 'items': items, 'total': data['total'],
                    'page': data['page'], 'per_page': data['per_page'], 'pages': data['pages']})


@platform_bp.route('/api/platform/posts', methods=['POST'])
def api_platform_posts_create():
    data = request.json or {}
    post_id, dup = content_storage.create_post(
        text=data.get('text', ''), media=data.get('media', ''),
        media_type=data.get('media_type', 'text'), caption=data.get('caption', ''),
        title=data.get('title', ''), category=data.get('category', ''),
        language=data.get('language', 'uz'), tags=data.get('tags', ''),
        source=data.get('source', 'manual'), source_url=data.get('source_url', ''),
        priority=int(data.get('priority', 5) or 5),
        status=data.get('status', 'available'))
    if post_id is None:
        return jsonify({'status': 'error', 'error': 'Duplicate or invalid'}), 400
    database.audit_log('post_create', f"post:{post_id}", new_value=data.get('text', '')[:100])
    return jsonify({'status': 'success', 'post_id': post_id, 'duplicate': bool(dup)})


@platform_bp.route('/api/platform/posts/<int:post_id>', methods=['GET'])
def api_platform_post_get(post_id):
    post = content_storage.get_post(post_id)
    if not post:
        return jsonify({'status': 'error', 'error': 'Not found'}), 404
    post['tags'] = content_storage.get_post_tags(post_id)
    return jsonify({'status': 'success', 'item': post})


@platform_bp.route('/api/platform/posts/<int:post_id>', methods=['PUT'])
def api_platform_post_update(post_id):
    data = request.json or {}
    fields = {k: v for k, v in data.items() if k in (
        'text', 'media', 'media_type', 'caption', 'title', 'category',
        'language', 'source', 'source_url', 'priority', 'status', 'tags')}
    tags = fields.pop('tags', None)
    if fields:
        content_storage.update_post(post_id, **fields)
    if tags is not None:
        conn = database._connect()
        content_storage._sync_tags(conn, post_id, tags)
        conn.close()
    database.audit_log('post_update', f"post:{post_id}", new_value=str(list(fields.keys())))
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/posts/<int:post_id>', methods=['DELETE'])
def api_platform_post_delete(post_id):
    content_storage.delete_post(post_id)
    database.audit_log('post_delete', f"post:{post_id}")
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/posts/<int:post_id>/archive', methods=['POST'])
def api_platform_post_archive(post_id):
    content_storage.archive_post(post_id)
    database.audit_log('post_archive', f"post:{post_id}")
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/posts/<int:post_id>/restore', methods=['POST'])
def api_platform_post_restore(post_id):
    content_storage.restore_post(post_id)
    database.audit_log('post_restore', f"post:{post_id}")
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/posts/<int:post_id>/duplicate', methods=['POST'])
def api_platform_post_duplicate(post_id):
    new_id = content_storage.duplicate_post(post_id)
    database.audit_log('post_duplicate', f"post:{post_id}", new_value=f"post:{new_id}")
    return jsonify({'status': 'success', 'post_id': new_id})


@platform_bp.route('/api/platform/posts/<int:post_id>/publish', methods=['POST'])
def api_platform_post_publish(post_id):
    data = request.json or {}
    username = data.get('channel', config.DEFAULT_CHANNEL)
    post = content_storage.get_post(post_id)
    if not post:
        return jsonify({'status': 'error', 'error': 'Not found'}), 404
    ok, err = scheduler_engine._publish(bot, post_id, username, post, int(time_now()))
    if not ok:
        return jsonify({'status': 'error', 'error': str(err)}), 500
    content_storage.update_post(post_id, status='published')
    content_storage.mark_used(post_id, username)
    ch_settings = channel_manager.ensure_settings(username)
    channel_id = ch_settings.get('channel_id')
    if not channel_id:
        conn = database._connect()
        c = conn.cursor()
        c.execute("SELECT id FROM managed_channels WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        channel_id = row[0] if row else None
    scheduler_engine.log_publication(post_id, channel_id, None, int(time_now()), 'SUCCESS')
    database.audit_log('post_publish', f"post:{post_id}", new_value=username)
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/storage/stats', methods=['GET'])
def api_platform_storage_stats():
    return jsonify({'status': 'success', 'stats': content_storage.storage_stats()})


@platform_bp.route('/api/platform/channels', methods=['GET'])
def api_platform_channels():
    items = channel_manager.channel_table()
    return jsonify({'status': 'success', 'items': items})


@platform_bp.route('/api/platform/channels/<path:username>', methods=['GET'])
def api_platform_channel_get(username):
    settings = channel_manager.get_settings(username)
    if not settings:
        return jsonify({'status': 'error', 'error': 'Not found'}), 404
    return jsonify({'status': 'success', 'item': settings})


@platform_bp.route('/api/platform/channels/<path:username>', methods=['PUT'])
def api_platform_channel_update(username):
    data = request.json or {}
    channel_manager.save_settings(username, data)
    scheduler_engine.log_event('settings_update', f"Channel {username} settings updated", data=str(list(data.keys())))
    database.audit_log('channel_update', username, new_value=str(list(data.keys())))
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/channels/<path:username>/delete', methods=['POST'])
def api_platform_channel_delete(username):
    channel_manager.delete_channel(username)
    database.audit_log('channel_delete', username)
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/channels/clone', methods=['POST'])
def api_platform_channels_clone():
    data = request.json or {}
    src = data.get('source')
    targets = data.get('targets', [])
    if not src or not targets:
        return jsonify({'status': 'error', 'error': 'source and targets required'}), 400
    count = channel_manager.clone_settings(src, targets)
    database.audit_log('channels_clone', src, new_value=", ".join(targets))
    return jsonify({'status': 'success', 'count': count})


@platform_bp.route('/api/platform/channels/bulk', methods=['POST'])
def api_platform_channels_bulk():
    data = request.json or {}
    channels = data.get('channels', [])
    updates = data.get('updates', {})
    if not channels or not updates:
        return jsonify({'status': 'error', 'error': 'channels and updates required'}), 400
    count = channel_manager.bulk_update(channels, updates)
    database.audit_log('channels_bulk', ", ".join(channels), new_value=str(updates))
    return jsonify({'status': 'success', 'count': count})


@platform_bp.route('/api/platform/networks', methods=['GET'])
def api_platform_networks():
    nets = channel_manager.get_networks()
    result = []
    for n in nets:
        result.append({
            'id': n['id'], 'name': n['name'], 'description': n['description'],
            'publications': n['publications'],
            'paused': channel_manager.is_network_paused(n['id']),
            'channels': [{'username': c} for c in channel_manager.network_channels(n['id'])]
        })
    return jsonify({'status': 'success', 'items': result})


@platform_bp.route('/api/platform/networks', methods=['POST'])
def api_platform_networks_create():
    data = request.json or {}
    nid = channel_manager.create_network(data.get('name', ''), data.get('description', ''))
    for ch in data.get('channels', []):
        if ch:
            channel_manager.add_channel_to_network(nid, ch)
    database.audit_log('network_create', data.get('name', ''), new_value=str(nid))
    return jsonify({'status': 'success', 'network_id': nid})


@platform_bp.route('/api/platform/networks/<int:nid>', methods=['PUT'])
def api_platform_network_update(nid):
    data = request.json or {}
    if 'name' in data:
        channel_manager.rename_network(nid, data['name'])
    if 'pause' in data:
        channel_manager.pause_network(nid, bool(data['pause']))
    database.audit_log('network_update', f"net:{nid}", new_value=str(data))
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/networks/<int:nid>', methods=['DELETE'])
def api_platform_network_delete(nid):
    channel_manager.delete_network(nid)
    database.audit_log('network_delete', f"net:{nid}")
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/networks/<int:nid>/channels', methods=['POST'])
def api_platform_network_channels(nid):
    data = request.json or {}
    action = data.get('action', 'add')
    username = data.get('username')
    if not username:
        return jsonify({'status': 'error', 'error': 'username required'}), 400
    if action == 'add':
        channel_manager.add_channel_to_network(nid, username)
    else:
        channel_manager.remove_channel_from_network(nid, username)
    database.audit_log('network_channel_' + action, f"net:{nid}", new_value=username)
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/networks/<int:nid>/clone', methods=['POST'])
def api_platform_network_clone(nid):
    data = request.json or {}
    new_id = channel_manager.clone_network(nid, data.get('name', ''))
    database.audit_log('network_clone', f"net:{nid}", new_value=f"net:{new_id}")
    return jsonify({'status': 'success', 'network_id': new_id})


@platform_bp.route('/api/platform/templates', methods=['GET'])
def api_platform_templates():
    items = [{'id': t['id'], 'name': t['name'], 'description': t['description'],
              'data': t['data'], 'created_at': t['created_at']} for t in channel_manager.get_templates()]
    return jsonify({'status': 'success', 'items': items})


@platform_bp.route('/api/platform/templates', methods=['POST'])
def api_platform_templates_create():
    data = request.json or {}
    tid = channel_manager.create_template(data.get('name', ''), data.get('description', ''), data.get('data', {}))
    database.audit_log('template_create', data.get('name', ''), new_value=str(tid))
    return jsonify({'status': 'success', 'template_id': tid})


@platform_bp.route('/api/platform/templates/<int:tid>', methods=['DELETE'])
def api_platform_template_delete(tid):
    channel_manager.delete_template(tid)
    database.audit_log('template_delete', f"tpl:{tid}")
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/templates/<int:tid>/apply', methods=['POST'])
def api_platform_template_apply(tid):
    data = request.json or {}
    channels = data.get('channels', [])
    count = channel_manager.apply_template(tid, channels)
    database.audit_log('template_apply', f"tpl:{tid}", new_value=", ".join(channels))
    return jsonify({'status': 'success', 'count': count})


@platform_bp.route('/api/platform/scheduler/run', methods=['POST'])
def api_platform_scheduler_run():
    data = request.json or {}
    dry_run = bool(data.get('dry_run', False))
    if data.get('test_mode') is not None:
        scheduler_engine.set_test_mode(bool(data['test_mode']))
    report = scheduler_engine.run_scheduler(bot, dry_run=dry_run)
    database.audit_log('scheduler_run', new_value=str(report))
    return jsonify({'status': 'success', 'report': report, 'test_mode': scheduler_engine.test_mode_enabled()})


@platform_bp.route('/api/platform/scheduler/test-mode', methods=['POST'])
def api_platform_scheduler_test_mode():
    data = request.json or {}
    scheduler_engine.set_test_mode(bool(data.get('enabled', False)))
    database.audit_log('test_mode', new_value=str(scheduler_engine.test_mode_enabled()))
    return jsonify({'status': 'success', 'test_mode': scheduler_engine.test_mode_enabled()})


@platform_bp.route('/api/platform/publications', methods=['GET'])
def api_platform_publications():
    status = request.args.get('status')
    channel_id = request.args.get('channel_id', type=int)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    data = scheduler_engine.publication_history(status=status, channel_id=channel_id, page=page, per_page=per_page)
    return jsonify({'status': 'success', **data})


@platform_bp.route('/api/platform/publications/retry', methods=['POST'])
def api_platform_publications_retry():
    done = scheduler_engine.retry_failed(bot)
    return jsonify({'status': 'success', 'retried': done})


@platform_bp.route('/api/platform/analytics', methods=['GET'])
def api_platform_analytics():
    return jsonify({'status': 'success', 'analytics': scheduler_engine.analytics()})


@platform_bp.route('/api/platform/events', methods=['GET'])
def api_platform_events():
    limit = int(request.args.get('limit', 100))
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("SELECT id, event_type, message, data, created_at FROM system_events ORDER BY id DESC LIMIT ?", (limit,))
    rows = [{'id': r[0], 'type': r[1], 'message': r[2], 'data': r[3], 'created_at': r[4]} for r in cur.fetchall()]
    conn.close()
    return jsonify({'status': 'success', 'items': rows})


@platform_bp.route('/api/platform/calendar', methods=['GET'])
def api_platform_calendar():
    day = request.args.get('day')
    return jsonify({'status': 'success', 'items': scheduler_engine.calendar_events(day)})


@platform_bp.route('/api/platform/settings', methods=['GET'])
def api_platform_settings():
    keys = ['test_mode', 'smart_queue_interval', 'notifications_enabled', 'default_channel', 'language', 'persona']
    out = {}
    for k in keys:
        out[k] = database.get_global_setting(k, '')
    out['admin_ids'] = list(getattr(config, 'ADMIN_IDS', []))
    out['default_channel'] = config.DEFAULT_CHANNEL
    return jsonify({'status': 'success', 'settings': out})


@platform_bp.route('/api/platform/settings', methods=['PUT'])
def api_platform_settings_update():
    data = request.json or {}
    for k, v in data.items():
        database.set_global_setting(k, str(v))
    scheduler_engine.log_event('settings_update', 'Global settings updated', data=str(list(data.keys())))
    database.audit_log('settings_update', new_value=str(data))
    return jsonify({'status': 'success'})


@platform_bp.route('/api/platform/audit', methods=['GET'])
def api_platform_audit():
    limit = int(request.args.get('limit', 200))
    action = request.args.get('action')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    if per_page > 500:
        per_page = 500
    conn = database._connect()
    cur = conn.cursor()
    where = ""
    args = []
    if action:
        where = "WHERE action = ?"
        args.append(action)
    cur.execute(f"SELECT COUNT(*) FROM audit_log {where}", args)
    total = cur.fetchone()[0]
    offset = (page - 1) * per_page
    cur.execute(
        f"SELECT id, user, action, target, old_value, new_value, created_at FROM audit_log {where} "
        f"ORDER BY id DESC LIMIT ? OFFSET ?", args + [per_page, offset])
    rows = cur.fetchall()
    conn.close()
    items = [{'id': r[0], 'user': r[1], 'action': r[2], 'target': r[3],
              'old_value': r[4], 'new_value': r[5], 'created_at': r[6]} for r in rows]
    pages = max(1, -(-total // per_page))
    return jsonify({'status': 'success', 'items': items, 'total': total,
                    'page': page, 'per_page': per_page, 'pages': pages})


@platform_bp.route('/platform')
def platform_page():
    return render_template('platform.html')


def time_now():
    import time
    return int(time.time())
