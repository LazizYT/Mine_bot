from flask import Flask, render_template, request, jsonify, send_file, Response
import database
import config
import os
import time
from datetime import datetime, timedelta
import pytz
import telebot
import publisher
import comments_analyzer
import ai_generator
import content_storage
import channel_manager
import scheduler_engine
from bot_instance import bot

app = Flask(__name__)

# Опциональная защита панели базовой авторизацией.
# Включается только если задан PANEL_PASSWORD в env. Иначе панель открыта (текущее поведение).
def _panel_auth_enabled():
    return bool(config.PANEL_PASSWORD)

@app.before_request
def _require_auth():
    if not _panel_auth_enabled():
        return None
    auth = request.authorization
    if auth and auth.username == config.PANEL_USER and auth.password == config.PANEL_PASSWORD:
        return None
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="MINE_BOT_OS"'})

file_path_cache = {}
# Кеш статистики подписчиков (не дёргать Telegram API на каждый запрос страницы)
_stats_cache = {'ts': 0, 'data': None}
_STATS_CACHE_TTL = 600  # 10 минут

def collect_stats():
    global _stats_cache
    now = time.time()
    if _stats_cache['data'] is not None and now - _stats_cache['ts'] < _STATS_CACHE_TTL:
        return _stats_cache['data']
    channels = database.get_all_managed_channels()
    for ch in channels:
        try:
            count = bot.get_chat_member_count(ch)
            database.save_sub_count(ch, count)
        except: pass
    _stats_cache = {'ts': now, 'data': True}
    return True

def get_telegram_file_url(file_id):
    if file_id in file_path_cache: return file_path_cache[file_id]
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{file_info.file_path}"
        file_path_cache[file_id] = url
        return url
    except: return None

def format_timestamp(ts):
    if not ts: return "⏰ ASAP"
    tz = pytz.timezone('Asia/Tashkent')
    return datetime.fromtimestamp(ts, tz).strftime('%d.%m %H:%M')

def collect_stats():
    channels = database.get_all_managed_channels()
    for ch in channels:
        try:
            count = bot.get_chat_member_count(ch)
            database.save_sub_count(ch, count)
        except: pass

def get_channel_growth(channel_id):
    history = database.get_sub_history(channel_id)
    if not history or len(history) < 2:
        return {'24h': 0, '7d': 0, '30d': 0, 'current': 0}
    
    current = history[-1][1]
    
    def get_diff(days):
        target_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        prev = next((h[1] for h in reversed(history) if h[0] <= target_date), history[0][1])
        return current - prev

    return {
        '24h': get_diff(1),
        '7d': get_diff(7),
        '30d': get_diff(30),
        'current': current
    }

@app.route('/api/ui-lang', methods=['POST'])
def set_ui_lang():
    lang = request.json.get('lang', 'uz')
    resp = jsonify({'status': 'success'})
    resp.set_cookie('ui_lang', lang, max_age=30*24*60*60)
    return resp

@app.route('/')
@app.route('/studio')
@app.route('/app')
def index():
    collect_stats()
    
    # --- ОПРЕДЕЛЕНИЕ ЯЗЫКА ИНТЕРФЕЙСА ---
    ui_lang = request.cookies.get('ui_lang', 'uz')
    import json
    try:
        with open('translations.json', 'r', encoding='utf-8') as f:
            all_translations = json.load(f)
        translations = all_translations.get(ui_lang, all_translations['uz'])
    except: translations = {}
    
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
            'time_str': format_timestamp(p[5]),
            'timestamp': p[5],
            'iso_time': datetime.fromtimestamp(p[5]).strftime('%Y-%m-%dT%H:%M') if p[5] else "",
            'files_count': len(doc_ids)
        })
    
    managed_channels = database.get_all_managed_channels()
    channel_stats = []
    total_subs = 0
    for ch in managed_channels:
        growth = get_channel_growth(ch)
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
            'time_str': format_timestamp(p[4]),
            'message_id': p[5]
        })
    
    import json
    with open('translations.json', 'r', encoding='utf-8') as f:
        translations = json.load(f)

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

@app.route('/api/watermarks/upload', methods=['POST'])
def upload_watermark():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'No file'}), 400
    
    # Проверка размера (макс 2МБ)
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

@app.route('/api/watermarks/activate/<int:wm_id>', methods=['POST'])
def activate_watermark(wm_id):
    database.set_active_watermark(wm_id)
    return jsonify({'status': 'success'})

@app.route('/api/watermarks/delete/<int:wm_id>', methods=['POST'])
def delete_watermark(wm_id):
    database.delete_watermark(wm_id)
    return jsonify({'status': 'success'})

@app.route('/api/settings/sq', methods=['POST'])
def set_sq_settings():
    data = request.json
    database.set_global_setting('smart_queue_interval', data.get('interval', '6'))
    database.set_global_setting('smart_queue_text', data.get('text', ''))
    return jsonify({'status': 'success'})

@app.route('/api/prompts/activate/<int:prompt_id>', methods=['POST'])
def api_activate_prompt(prompt_id):
    database.activate_prompt(prompt_id)
    return jsonify({'status': 'success'})

@app.route('/api/prompts/update/<int:prompt_id>', methods=['POST'])
def api_update_prompt(prompt_id):
    data = request.json
    database.update_prompt(prompt_id, data.get('name'), data.get('prompt'))
    return jsonify({'status': 'success'})

@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    return jsonify(database.get_all_prompts())

@app.route('/api/prompts/add', methods=['POST'])
def add_prompt():
    data = request.json
    database.add_prompt(data.get('name'), data.get('prompt'))
    return jsonify({'status': 'success'})

@app.route('/api/prompts/delete/<int:prompt_id>', methods=['POST'])
def delete_prompt(prompt_id):
    database.delete_prompt(prompt_id)
    return jsonify({'status': 'success'})

@app.route('/api/comments', methods=['GET'])
def get_comments():
    comments = database.get_all_comments()
    return jsonify([{'user': c[0], 'text': c[1]} for c in comments])

@app.route('/api/comments/analyze', methods=['POST'])
def analyze_comments_api():
    summary = comments_analyzer.analyze_comments()
    return jsonify({'summary': summary})

@app.route('/api/comments/clear', methods=['POST'])
def clear_comments_api():
    database.clear_comments()
    return jsonify({'status': 'success'})

@app.route('/api/settings/ad', methods=['POST'])
def set_ad():
    text = request.json.get('text', '')
    database.set_global_setting('ad_text', text)
    return jsonify({'status': 'success'})

@app.route('/api/settings/language', methods=['POST'])
def set_language():
    lang = request.json.get('lang')
    if lang in ['uz', 'ru', 'en']:
        for admin_id in config.ADMIN_IDS:
            database.update_user_setting(admin_id, 'persona', lang)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

@app.route('/api/delete/<int:post_id>', methods=['POST'])
def api_delete_post(post_id):
    database.delete_from_queue(post_id)
    return jsonify({'status': 'success'})

@app.route('/api/prompts/improve', methods=['POST'])
def api_improve_prompt():
    desc = request.json.get('desc', '')
    if not desc: return jsonify({'error': 'Empty description'}), 400
    return jsonify({'improved': ai_generator.improve_prompt(desc)})

@app.route('/api/prompts/select', methods=['POST'])
def api_select_prompt():
    prompt_id = request.json.get('id')
    if prompt_id:
        database.activate_prompt(prompt_id)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

@app.route('/api/settings/interval', methods=['POST'])
def api_set_interval():
    interval = request.json.get('interval', '6')
    database.set_global_setting('smart_queue_interval', str(interval))
    return jsonify({'status': 'success'})

@app.route('/api/system/clear-memory', methods=['POST'])
def api_clear_memory():
    database.clear_comments()
    return jsonify({'status': 'success'})

@app.route('/api/upload/logo', methods=['POST'])
def api_upload_logo():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'No file'}), 400
    filename = f"wm_{int(time.time())}.png"
    path = os.path.join('data', filename)
    file.save(path)
    if database.add_watermark_db(path, file.filename):
        # Автоматически активируем новый логотип
        wms = database.get_all_watermarks()
        for wm in wms:
            if wm[1] == path:
                database.set_active_watermark(wm[0])
                break
        return jsonify({'status': 'success'})
    os.remove(path)
    return jsonify({'error': 'Limit reached (max 5)'}), 400

@app.route('/api/analytics')
def api_analytics():
    return jsonify(database.get_post_stats())

@app.route('/api/memory', methods=['GET'])
def api_get_memory():
    notes = database.get_memory_notes()
    return jsonify([{'id': n[0], 'note': n[1], 'created_at': n[2]} for n in notes])

@app.route('/api/memory', methods=['POST'])
def api_add_memory():
    note = (request.json or {}).get('note', '').strip()
    if not note:
        return jsonify({'error': 'Empty note'}), 400
    database.add_memory_note(note)
    return jsonify({'status': 'success'})

@app.route('/api/memory/<int:note_id>', methods=['DELETE'])
def api_delete_memory(note_id):
    database.delete_memory_note(note_id)
    return jsonify({'status': 'success'})

@app.route('/api/memory/clear', methods=['POST'])
def api_clear_ai_memory():
    database.clear_memory_notes()
    return jsonify({'status': 'success'})

@app.route('/logo.png')
def get_logo():
    path = os.path.join('templates', 'logo.png')
    if os.path.exists(path): return send_file(path, mimetype='image/png')
    return "Not found", 404

@app.route('/api/publish/<int:post_id>', methods=['POST'])
def api_publish_now(post_id):
    post = database.get_post_by_id(post_id)
    if post and publisher.publish_post_data(bot, post[0], post[1], post[2], post[3], post[4] or config.DEFAULT_CHANNEL):
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

@app.route('/api/stats')
def get_stats_data():
    channels = database.get_all_managed_channels()
    result = {}
    for ch in channels:
        history = database.get_sub_history(ch)
        result[ch] = {'labels': [h[0] for h in history], 'data': [h[1] for h in history]}
    return jsonify(result)

@app.route('/api/channels', methods=['POST'])
def api_add_channel():
    username = request.json.get('username')
    if username:
        if not username.startswith('@'): username = '@' + username
        database.add_channel(username)
    return jsonify({'status': 'success'})

@app.route('/api/channels/delete', methods=['POST'])
def api_remove_channel():
    username = request.json.get('username')
    database.remove_channel(username)
    return jsonify({'status': 'success'})

@app.route('/file/<path:file_id>')
def serve_file(file_id):
    # Локальные файлы (водяные знаки, логотип)
    if not file_id.startswith('AgAC') and not file_id.startswith('file_') and ('.' in file_id or '/' in file_id or '\\' in file_id):
        for folder in ['data', 'templates']:
            path = os.path.join(folder, os.path.basename(file_id))
            if os.path.exists(path):
                return send_file(path)
    # Telegram file_id — проксируем через бота (без утечки токена в URL, работает в WebApp)
    try:
        from io import BytesIO
        file_info = bot.get_file(file_id)
        data = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path or '')[1] or '.jpg'
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'webp': 'image/webp', 'gif': 'image/gif'}.get(ext.lstrip('.').lower(), 'image/jpeg')
        return send_file(BytesIO(data), mimetype=mime, download_name=f"file_{file_id}{ext}")
    except Exception as e:
        print(f"❌ Ошибка загрузки файла {file_id}: {e}")
        return "Not found", 404

@app.route('/api/post/<int:post_id>')
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

@app.route('/api/delete-file/<int:post_id>/<int:file_idx>', methods=['POST'])
def delete_file(post_id, file_idx):
    post = database.get_post_by_id(post_id)
    if not post: return jsonify({'error': 'Post not found'}), 404
    
    # post[3] - это document_id, строка с путями или ID файлов через запятую
    doc_ids = post[3].split(',') if post[3] else []
    if 0 <= file_idx < len(doc_ids):
        doc_ids.pop(file_idx)
        new_doc_ids = ",".join(doc_ids)
        
        # Обновляем БД (нужен метод, который обновит только document_id)
        # Пока используем простую SQL-команду через sqlite3 напрямую, 
        # так как подходящего метода в database.py нет.
        import sqlite3
        conn = sqlite3.connect(database.DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE queue SET document_id = ? WHERE id = ?", (new_doc_ids, post_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Invalid file index'}), 400

@app.route('/api/edit/<int:post_id>', methods=['POST'])
def edit_post(post_id):
    data = request.json
    text = data.get('text')
    iso_time = data.get('time')
    try:
        tz = pytz.timezone('Asia/Tashkent')
        dt = datetime.fromisoformat(iso_time)
        timestamp = int(tz.localize(dt).timestamp())
    except: timestamp = data.get('timestamp')
    database.update_post_content(post_id, text, timestamp)
    return jsonify({'status': 'success'})

@app.route('/api/reorder', methods=['POST'])
def reorder():
    order = request.json.get('order')
    if not order: return jsonify({'status': 'error'})
    
    pending = database.get_all_pending()
    # Собираем все существующие временные метки или генерируем новые, если их нет
    existing_timestamps = sorted([p[5] for p in pending if p[5]])
    
    # Если меток меньше чем постов, генерируем недостающие
    interval = int(database.get_global_setting('smart_queue_interval', 6)) * 3600
    last_time = existing_timestamps[-1] if existing_timestamps else int(time.time())
    
    # Создаем полный список таймстампов для всех ID в новом порядке
    new_timestamps = []
    if existing_timestamps:
        # Если были старые времена, пытаемся их переиспользовать
        new_timestamps = existing_timestamps
        while len(new_timestamps) < len(order):
            last_time += interval
            new_timestamps.append(last_time)
    else:
        # Если все посты были "ASAP", создаем новую последовательность
        for i in range(len(order)):
            new_timestamps.append(last_time + (i * interval))

    # Обновляем каждый пост в базе
    for i, p_id in enumerate(order):
        if p_id is None: continue
        post = database.get_post_by_id(int(p_id))
        if post:
            database.update_post_content(post[0], post[2], new_timestamps[i])
            
    return jsonify({'status': 'success'})

# ---------------------------------------------------------------------------
# CONTENT DISTRIBUTION PLATFORM API (Фазы 7-8)
# ---------------------------------------------------------------------------

@app.route('/api/platform/posts', methods=['GET'])
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


@app.route('/api/platform/posts', methods=['POST'])
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
    return jsonify({'status': 'success', 'post_id': post_id, 'duplicate': bool(dup)})


@app.route('/api/platform/posts/<int:post_id>', methods=['GET'])
def api_platform_post_get(post_id):
    post = content_storage.get_post(post_id)
    if not post:
        return jsonify({'status': 'error', 'error': 'Not found'}), 404
    post['tags'] = content_storage.get_post_tags(post_id)
    return jsonify({'status': 'success', 'item': post})


@app.route('/api/platform/posts/<int:post_id>', methods=['PUT'])
def api_platform_post_update(post_id):
    data = request.json or {}
    fields = {k: v for k, v in data.items() if k in (
        'text', 'media', 'media_type', 'caption', 'title', 'category',
        'language', 'source', 'source_url', 'priority', 'status', 'tags')}
    if 'tags' in fields:
        tags = fields.pop('tags')
    else:
        tags = None
    if fields:
        content_storage.update_post(post_id, **fields)
    if tags is not None:
        conn = database._connect()
        content_storage._sync_tags(conn, post_id, tags)
        conn.close()
    return jsonify({'status': 'success'})


@app.route('/api/platform/posts/<int:post_id>', methods=['DELETE'])
def api_platform_post_delete(post_id):
    content_storage.delete_post(post_id)
    return jsonify({'status': 'success'})


@app.route('/api/platform/posts/<int:post_id>/archive', methods=['POST'])
def api_platform_post_archive(post_id):
    content_storage.archive_post(post_id)
    return jsonify({'status': 'success'})


@app.route('/api/platform/posts/<int:post_id>/restore', methods=['POST'])
def api_platform_post_restore(post_id):
    content_storage.restore_post(post_id)
    return jsonify({'status': 'success'})


@app.route('/api/platform/posts/<int:post_id>/duplicate', methods=['POST'])
def api_platform_post_duplicate(post_id):
    new_id = content_storage.duplicate_post(post_id)
    return jsonify({'status': 'success', 'post_id': new_id})


@app.route('/api/platform/posts/<int:post_id>/publish', methods=['POST'])
def api_platform_post_publish(post_id):
    data = request.json or {}
    username = data.get('channel', config.DEFAULT_CHANNEL)
    post = content_storage.get_post(post_id)
    if not post:
        return jsonify({'status': 'error', 'error': 'Not found'}), 404
    ok, err = scheduler_engine._publish(bot, post_id, username, post, int(time.time()))
    if not ok:
        return jsonify({'status': 'error', 'error': str(err)}), 500
    content_storage.update_post(post_id, status='published')
    content_storage.mark_used(post_id, username)
    ch_settings = channel_manager.ensure_settings(username)
    channel_id = ch_settings.get('channel_id')
    if not channel_id:
        import sqlite3
        conn = sqlite3.connect(database.DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM managed_channels WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        channel_id = row[0] if row else None
    scheduler_engine.log_publication(post_id, channel_id, None, int(time.time()), 'SUCCESS')
    return jsonify({'status': 'success'})


@app.route('/api/platform/storage/stats', methods=['GET'])
def api_platform_storage_stats():
    return jsonify({'status': 'success', 'stats': content_storage.storage_stats()})


@app.route('/api/platform/channels', methods=['GET'])
def api_platform_channels():
    items = channel_manager.channel_table()
    return jsonify({'status': 'success', 'items': items})


@app.route('/api/platform/channels/<path:username>', methods=['GET'])
def api_platform_channel_get(username):
    settings = channel_manager.get_settings(username)
    if not settings:
        return jsonify({'status': 'error', 'error': 'Not found'}), 404
    return jsonify({'status': 'success', 'item': settings})


@app.route('/api/platform/channels/<path:username>', methods=['PUT'])
def api_platform_channel_update(username):
    data = request.json or {}
    channel_manager.save_settings(username, data)
    scheduler_engine.log_event('settings_update', f"Channel {username} settings updated", data=str(list(data.keys())))
    return jsonify({'status': 'success'})


@app.route('/api/platform/channels/<path:username>/delete', methods=['POST'])
def api_platform_channel_delete(username):
    channel_manager.delete_channel(username)
    return jsonify({'status': 'success'})


@app.route('/api/platform/channels/clone', methods=['POST'])
def api_platform_channels_clone():
    data = request.json or {}
    src = data.get('source')
    targets = data.get('targets', [])
    if not src or not targets:
        return jsonify({'status': 'error', 'error': 'source and targets required'}), 400
    count = channel_manager.clone_settings(src, targets)
    return jsonify({'status': 'success', 'count': count})


@app.route('/api/platform/channels/bulk', methods=['POST'])
def api_platform_channels_bulk():
    data = request.json or {}
    channels = data.get('channels', [])
    updates = data.get('updates', {})
    if not channels or not updates:
        return jsonify({'status': 'error', 'error': 'channels and updates required'}), 400
    count = channel_manager.bulk_update(channels, updates)
    return jsonify({'status': 'success', 'count': count})


@app.route('/api/platform/networks', methods=['GET'])
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


@app.route('/api/platform/networks', methods=['POST'])
def api_platform_networks_create():
    data = request.json or {}
    nid = channel_manager.create_network(data.get('name', ''), data.get('description', ''))
    for ch in data.get('channels', []):
        if ch:
            channel_manager.add_channel_to_network(nid, ch)
    return jsonify({'status': 'success', 'network_id': nid})


@app.route('/api/platform/networks/<int:nid>', methods=['PUT'])
def api_platform_network_update(nid):
    data = request.json or {}
    if 'name' in data:
        channel_manager.rename_network(nid, data['name'])
    if 'pause' in data:
        channel_manager.pause_network(nid, bool(data['pause']))
    return jsonify({'status': 'success'})


@app.route('/api/platform/networks/<int:nid>', methods=['DELETE'])
def api_platform_network_delete(nid):
    channel_manager.delete_network(nid)
    return jsonify({'status': 'success'})


@app.route('/api/platform/networks/<int:nid>/channels', methods=['POST'])
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
    return jsonify({'status': 'success'})


@app.route('/api/platform/networks/<int:nid>/clone', methods=['POST'])
def api_platform_network_clone(nid):
    data = request.json or {}
    new_id = channel_manager.clone_network(nid, data.get('name', ''))
    return jsonify({'status': 'success', 'network_id': new_id})


@app.route('/api/platform/templates', methods=['GET'])
def api_platform_templates():
    items = [{'id': t['id'], 'name': t['name'], 'description': t['description'],
              'data': t['data'], 'created_at': t['created_at']} for t in channel_manager.get_templates()]
    return jsonify({'status': 'success', 'items': items})


@app.route('/api/platform/templates', methods=['POST'])
def api_platform_templates_create():
    data = request.json or {}
    tid = channel_manager.create_template(data.get('name', ''), data.get('description', ''), data.get('data', {}))
    return jsonify({'status': 'success', 'template_id': tid})


@app.route('/api/platform/templates/<int:tid>', methods=['DELETE'])
def api_platform_template_delete(tid):
    channel_manager.delete_template(tid)
    return jsonify({'status': 'success'})


@app.route('/api/platform/templates/<int:tid>/apply', methods=['POST'])
def api_platform_template_apply(tid):
    data = request.json or {}
    channels = data.get('channels', [])
    count = channel_manager.apply_template(tid, channels)
    return jsonify({'status': 'success', 'count': count})


@app.route('/api/platform/scheduler/run', methods=['POST'])
def api_platform_scheduler_run():
    data = request.json or {}
    dry_run = bool(data.get('dry_run', False))
    if data.get('test_mode') is not None:
        scheduler_engine.set_test_mode(bool(data['test_mode']))
    report = scheduler_engine.run_scheduler(bot, dry_run=dry_run)
    return jsonify({'status': 'success', 'report': report, 'test_mode': scheduler_engine.test_mode_enabled()})


@app.route('/api/platform/scheduler/test-mode', methods=['POST'])
def api_platform_scheduler_test_mode():
    data = request.json or {}
    scheduler_engine.set_test_mode(bool(data.get('enabled', False)))
    return jsonify({'status': 'success', 'test_mode': scheduler_engine.test_mode_enabled()})


@app.route('/api/platform/publications', methods=['GET'])
def api_platform_publications():
    status = request.args.get('status')
    channel_id = request.args.get('channel_id', type=int)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    data = scheduler_engine.publication_history(status=status, channel_id=channel_id, page=page, per_page=per_page)
    return jsonify({'status': 'success', **data})


@app.route('/api/platform/publications/retry', methods=['POST'])
def api_platform_publications_retry():
    done = scheduler_engine.retry_failed(bot)
    return jsonify({'status': 'success', 'retried': done})


@app.route('/api/platform/analytics', methods=['GET'])
def api_platform_analytics():
    return jsonify({'status': 'success', 'analytics': scheduler_engine.analytics()})


@app.route('/api/platform/events', methods=['GET'])
def api_platform_events():
    limit = int(request.args.get('limit', 100))
    conn = database._connect()
    cur = conn.cursor()
    cur.execute("SELECT id, event_type, message, data, created_at FROM system_events ORDER BY id DESC LIMIT ?", (limit,))
    rows = [{'id': r[0], 'type': r[1], 'message': r[2], 'data': r[3], 'created_at': r[4]} for r in cur.fetchall()]
    conn.close()
    return jsonify({'status': 'success', 'items': rows})


@app.route('/api/platform/calendar', methods=['GET'])
def api_platform_calendar():
    day = request.args.get('day')
    return jsonify({'status': 'success', 'items': scheduler_engine.calendar_events(day)})


@app.route('/api/platform/settings', methods=['GET'])
def api_platform_settings():
    keys = ['test_mode', 'smart_queue_interval', 'notifications_enabled', 'default_channel', 'language', 'persona']
    out = {}
    for k in keys:
        out[k] = database.get_global_setting(k, '')
    out['admin_ids'] = list(getattr(config, 'ADMIN_IDS', []))
    out['default_channel'] = config.DEFAULT_CHANNEL
    return jsonify({'status': 'success', 'settings': out})


@app.route('/api/platform/settings', methods=['PUT'])
def api_platform_settings_update():
    data = request.json or {}
    for k, v in data.items():
        database.set_global_setting(k, str(v))
    scheduler_engine.log_event('settings_update', 'Global settings updated', data=str(list(data.keys())))
    return jsonify({'status': 'success'})


@app.route('/platform')
def platform_page():
    return render_template('platform.html')


def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

