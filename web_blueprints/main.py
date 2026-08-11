"""Дашборд и legacy API (не /api/platform/*)."""
import json
import os
import time
from datetime import datetime

from flask import render_template, request, jsonify, send_file
from io import BytesIO

import config
import database
import ai_generator
import comments_analyzer
import publisher
import web_helpers
from bot_instance import bot
from web_blueprints import main_bp


@main_bp.route('/api/ui-lang', methods=['POST'])
def set_ui_lang():
    lang = request.json.get('lang', 'uz')
    resp = jsonify({'status': 'success'})
    resp.set_cookie('ui_lang', lang, max_age=30 * 24 * 60 * 60)
    return resp


@main_bp.route('/')
@main_bp.route('/studio')
@main_bp.route('/app')
def index():
    web_helpers.collect_stats()

    ui_lang = request.cookies.get('ui_lang', 'uz')
    try:
        with open('translations.json', 'r', encoding='utf-8') as f:
            all_translations = json.load(f)
        translations = all_translations.get(ui_lang, all_translations['uz'])
    except Exception:
        translations = {}

    stats = database.get_stats()
    pending = database.get_all_pending()
    queue = []
    for p in pending:
        doc_ids = p[3].split(',') if p[3] else []
        queue.append({
            'id': p[0],
            'photos': p[1].split(',') if p[1] else [],
            'text': p[2],
            'channel': p[4] or config.DEFAULT_CHANNEL,
            'time_str': web_helpers.format_timestamp(p[5]),
            'timestamp': p[5],
            'iso_time': datetime.fromtimestamp(p[5]).strftime('%Y-%m-%dT%H:%M') if p[5] else "",
            'files_count': len(doc_ids)
        })

    managed_channels = database.get_all_managed_channels()
    channel_stats = []
    total_subs = 0
    for ch in managed_channels:
        growth = web_helpers.get_channel_growth(ch)
        total_subs += growth['current']
        channel_stats.append({
            'username': ch,
            'subs': growth['current'],
            'g24h': growth['24h'],
            'g7d': growth['7d'],
            'g30d': growth['30d']
        })

    current_lang = database.get_user_setting(config.ADMIN_IDS[0], 'persona', 'uz')
    ad_text = database.get_global_setting('ad_text', '')
    sq_interval = database.get_global_setting('smart_queue_interval', '6')
    sq_text = database.get_global_setting('smart_queue_text', '')

    watermarks = database.get_all_watermarks()
    active_prompt, active_prompt_id = database.get_active_prompt()

    published_raw = database.get_published_history(50)
    history = []
    for p in published_raw:
        history.append({
            'id': p[0],
            'photos': p[1].split(',') if p[1] else [],
            'text': p[2],
            'channel': p[3],
            'time_str': web_helpers.format_timestamp(p[4]),
            'message_id': p[5]
        })

    try:
        with open('translations.json', 'r', encoding='utf-8') as f:
            translations = json.load(f)
    except Exception:
        translations = {}

    post_stats = database.get_post_stats()

    return render_template('dashboard.html', stats=stats, queue=queue,
                           history=history,
                           channels=channel_stats, total_subs=total_subs,
                           current_lang=current_lang, ad_text=ad_text,
                           sq_interval=sq_interval, sq_text=sq_text,
                           watermarks=watermarks, active_prompt=active_prompt,
                           active_prompt_id=active_prompt_id,
                           post_stats=post_stats,
                           translations=translations,
                           config=config)


@main_bp.route('/api/watermarks/upload', methods=['POST'])
def upload_watermark():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file'}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({'error': 'File too large (max 2MB)'}), 400

    filename = f"wm_{int(time.time())}.png"
    path = os.path.join('data', filename)
    file.save(path)

    if database.add_watermark_db(path, file.filename):
        return jsonify({'status': 'success'})
    else:
        os.remove(path)
        return jsonify({'error': 'Limit reached (max 5)'}), 400


@main_bp.route('/api/watermarks/activate/<int:wm_id>', methods=['POST'])
def activate_watermark(wm_id):
    database.set_active_watermark(wm_id)
    return jsonify({'status': 'success'})


@main_bp.route('/api/watermarks/delete/<int:wm_id>', methods=['POST'])
def delete_watermark(wm_id):
    database.delete_watermark(wm_id)
    return jsonify({'status': 'success'})


@main_bp.route('/api/settings/sq', methods=['POST'])
def set_sq_settings():
    data = request.json
    database.set_global_setting('smart_queue_interval', data.get('interval', '6'))
    database.set_global_setting('smart_queue_text', data.get('text', ''))
    return jsonify({'status': 'success'})


@main_bp.route('/api/prompts/activate/<int:prompt_id>', methods=['POST'])
def api_activate_prompt(prompt_id):
    database.activate_prompt(prompt_id)
    return jsonify({'status': 'success'})


@main_bp.route('/api/prompts/update/<int:prompt_id>', methods=['POST'])
def api_update_prompt(prompt_id):
    data = request.json
    database.update_prompt(prompt_id, data.get('name'), data.get('prompt'))
    return jsonify({'status': 'success'})


@main_bp.route('/api/prompts', methods=['GET'])
def get_prompts():
    return jsonify(database.get_all_prompts())


@main_bp.route('/api/prompts/add', methods=['POST'])
def add_prompt():
    data = request.json
    database.add_prompt(data.get('name'), data.get('prompt'))
    return jsonify({'status': 'success'})


@main_bp.route('/api/prompts/delete/<int:prompt_id>', methods=['POST'])
def delete_prompt(prompt_id):
    database.delete_prompt(prompt_id)
    return jsonify({'status': 'success'})


@main_bp.route('/api/comments', methods=['GET'])
def get_comments():
    comments = database.get_all_comments()
    return jsonify([{'user': c[0], 'text': c[1]} for c in comments])


@main_bp.route('/api/comments/analyze', methods=['POST'])
def analyze_comments_api():
    summary = comments_analyzer.analyze_comments()
    return jsonify({'summary': summary})


@main_bp.route('/api/comments/clear', methods=['POST'])
def clear_comments_api():
    database.clear_comments()
    return jsonify({'status': 'success'})


@main_bp.route('/api/settings/ad', methods=['POST'])
def set_ad():
    text = request.json.get('text', '')
    database.set_global_setting('ad_text', text)
    return jsonify({'status': 'success'})


@main_bp.route('/api/settings/language', methods=['POST'])
def set_language():
    lang = request.json.get('lang')
    if lang in ['uz', 'ru', 'en']:
        for admin_id in config.ADMIN_IDS:
            database.update_user_setting(admin_id, 'persona', lang)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400


@main_bp.route('/api/delete/<int:post_id>', methods=['POST'])
def api_delete_post(post_id):
    database.delete_from_queue(post_id)
    return jsonify({'status': 'success'})


@main_bp.route('/api/prompts/improve', methods=['POST'])
def api_improve_prompt():
    desc = request.json.get('desc', '')
    if not desc:
        return jsonify({'error': 'Empty description'}), 400
    return jsonify({'improved': ai_generator.improve_prompt(desc)})


@main_bp.route('/api/prompts/select', methods=['POST'])
def api_select_prompt():
    prompt_id = request.json.get('id')
    if prompt_id:
        database.activate_prompt(prompt_id)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400


@main_bp.route('/api/settings/interval', methods=['POST'])
def api_set_interval():
    interval = request.json.get('interval', '6')
    database.set_global_setting('smart_queue_interval', str(interval))
    return jsonify({'status': 'success'})


@main_bp.route('/api/system/clear-memory', methods=['POST'])
def api_clear_memory():
    database.clear_comments()
    return jsonify({'status': 'success'})


@main_bp.route('/api/upload/logo', methods=['POST'])
def api_upload_logo():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file'}), 400
    filename = f"wm_{int(time.time())}.png"
    path = os.path.join('data', filename)
    file.save(path)
    if database.add_watermark_db(path, file.filename):
        wms = database.get_all_watermarks()
        for wm in wms:
            if wm[1] == path:
                database.set_active_watermark(wm[0])
                break
        return jsonify({'status': 'success'})
    os.remove(path)
    return jsonify({'error': 'Limit reached (max 5)'}), 400


@main_bp.route('/api/analytics')
def api_analytics():
    return jsonify(database.get_post_stats())


@main_bp.route('/api/memory', methods=['GET'])
def api_get_memory():
    notes = database.get_memory_notes()
    return jsonify([{'id': n[0], 'note': n[1], 'created_at': n[2]} for n in notes])


@main_bp.route('/api/memory', methods=['POST'])
def api_add_memory():
    note = (request.json or {}).get('note', '').strip()
    if not note:
        return jsonify({'error': 'Empty note'}), 400
    database.add_memory_note(note)
    return jsonify({'status': 'success'})


@main_bp.route('/api/memory/<int:note_id>', methods=['DELETE'])
def api_delete_memory(note_id):
    database.delete_memory_note(note_id)
    return jsonify({'status': 'success'})


@main_bp.route('/api/memory/clear', methods=['POST'])
def api_clear_ai_memory():
    database.clear_memory_notes()
    return jsonify({'status': 'success'})


@main_bp.route('/logo.png')
def get_logo():
    path = os.path.join('templates', 'logo.png')
    if os.path.exists(path):
        return send_file(path, mimetype='image/png')
    return "Not found", 404


@main_bp.route('/api/publish/<int:post_id>', methods=['POST'])
def api_publish_now(post_id):
    post = database.get_post_by_id(post_id)
    if post and publisher.publish_post_data(bot, post[0], post[1], post[2], post[3], post[4] or config.DEFAULT_CHANNEL):
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400


@main_bp.route('/api/stats')
def get_stats_data():
    channels = database.get_all_managed_channels()
    result = {}
    for ch in channels:
        history = database.get_sub_history(ch)
        result[ch] = {'labels': [h[0] for h in history], 'data': [h[1] for h in history]}
    return jsonify(result)


@main_bp.route('/api/channels', methods=['POST'])
def api_add_channel():
    username = request.json.get('username')
    if username:
        if not username.startswith('@'):
            username = '@' + username
        database.add_channel(username)
    return jsonify({'status': 'success'})


@main_bp.route('/api/channels/delete', methods=['POST'])
def api_remove_channel():
    username = request.json.get('username')
    database.remove_channel(username)
    return jsonify({'status': 'success'})


@main_bp.route('/file/<path:file_id>')
def serve_file(file_id):
    if not file_id.startswith('AgAC') and not file_id.startswith('file_') and ('.' in file_id or '/' in file_id or '\\' in file_id):
        for folder in ['data', 'templates']:
            path = os.path.join(folder, os.path.basename(file_id))
            if os.path.exists(path):
                return send_file(path)
    try:
        file_info = bot.get_file(file_id)
        data = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path or '')[1] or '.jpg'
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'webp': 'image/webp', 'gif': 'image/gif'}.get(ext.lstrip('.').lower(), 'image/jpeg')
        return send_file(BytesIO(data), mimetype=mime, download_name=f"file_{file_id}{ext}")
    except Exception as e:
        print(f"❌ Ошибка загрузки файла {file_id}: {e}")
        return "Not found", 404


@main_bp.route('/api/post/<int:post_id>')
def api_get_post(post_id):
    post = database.get_post_by_id(post_id)
    if not post:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'id': post[0],
        'photos': post[1].split(',') if post[1] else [],
        'text': post[2],
        'document_id': post[3],
        'channel': post[4] or config.DEFAULT_CHANNEL,
        'timestamp': post[5],
        'iso_time': datetime.fromtimestamp(post[5]).strftime('%Y-%m-%dT%H:%M') if post[5] else ""
    })


@main_bp.route('/api/delete-file/<int:post_id>/<int:file_idx>', methods=['POST'])
def delete_file(post_id, file_idx):
    post = database.get_post_by_id(post_id)
    if not post:
        return jsonify({'error': 'Post not found'}), 404

    doc_ids = post[3].split(',') if post[3] else []
    if 0 <= file_idx < len(doc_ids):
        doc_ids.pop(file_idx)
        new_doc_ids = ",".join(doc_ids)
        conn = database._connect()
        c = conn.cursor()
        c.execute("UPDATE queue SET document_id = ? WHERE id = ?", (new_doc_ids, post_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Invalid file index'}), 400


@main_bp.route('/api/edit/<int:post_id>', methods=['POST'])
def edit_post(post_id):
    import pytz
    data = request.json
    text = data.get('text')
    iso_time = data.get('time')
    try:
        tz = pytz.timezone('Asia/Tashkent')
        dt = datetime.fromisoformat(iso_time)
        timestamp = int(tz.localize(dt).timestamp())
    except Exception:
        timestamp = data.get('timestamp')
    database.update_post_content(post_id, text, timestamp)
    return jsonify({'status': 'success'})


@main_bp.route('/api/reorder', methods=['POST'])
def reorder():
    order = request.json.get('order')
    if not order:
        return jsonify({'status': 'error'})

    pending = database.get_all_pending()
    existing_timestamps = sorted([p[5] for p in pending if p[5]])

    interval = int(database.get_global_setting('smart_queue_interval', 6)) * 3600
    last_time = existing_timestamps[-1] if existing_timestamps else int(time.time())

    new_timestamps = []
    if existing_timestamps:
        new_timestamps = existing_timestamps
        while len(new_timestamps) < len(order):
            last_time += interval
            new_timestamps.append(last_time)
    else:
        for i in range(len(order)):
            new_timestamps.append(last_time + (i * interval))

    for i, p_id in enumerate(order):
        if p_id is None:
            continue
        post = database.get_post_by_id(int(p_id))
        if post:
            database.update_post_content(post[0], post[2], new_timestamps[i])

    return jsonify({'status': 'success'})
