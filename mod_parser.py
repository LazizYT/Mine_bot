import requests
import re
import config

def parse_mod_data(url):
    """
    Определяет тип ссылки и извлекает данные.
    Поддерживает CurseForge и Modrinth.
    """
    if "curseforge.com" in url:
        return parse_curseforge(url)
    elif "modrinth.com" in url:
        return parse_modrinth(url)
    return None

def parse_modrinth(url):
    """Извлекает данные через официальный Modrinth API (Labrinth). API-ключ не требуется."""
    try:
        # Пример: https://modrinth.com/mod/sodium
        slug = url.rstrip('/').split('/')[-1]
        resp = requests.get(f"https://api.modrinth.com/v2/project/{slug}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            game_versions = data.get('game_versions', [])
            return {
                'title': data.get('title'),
                'summary': data.get('description'),
                'version': game_versions[0] if game_versions else 'N/A',
                'downloads': data.get('downloads'),
                'source': 'Modrinth'
            }
    except Exception as e:
        print(f"Modrinth Parser Error: {e}")
    return None

def parse_curseforge(url):
    """Извлекает данные через CurseForge API (требует API ключ)."""
    try:
        # Извлекаем projectID из URL (обычно в конце)
        # Пример: https://www.curseforge.com/minecraft/mc-mods/jei
        project_slug = url.split('/')[-1]
        
        headers = {
            'x-api-key': config.CURSEFORGE_API_KEY,
            'Accept': 'application/json'
        }
        
        # Сначала ищем ID по слагу
        search_url = f"https://api.curseforge.com/v1/mods/search?gameId=432&slug={project_slug}"
        resp = requests.get(search_url, headers=headers, timeout=10)
        data = resp.json().get('data', [])
        
        if data:
            mod = data[0]
            return {
                'title': mod.get('name'),
                'summary': mod.get('summary'),
                'version': mod.get('latestFiles', [{}])[0].get('displayName', 'N/A'),
                'downloads': mod.get('downloadCount'),
                'source': 'CurseForge'
            }
    except Exception as e:
        print(f"CurseForge Parser Error: {e}")
    return None

def search_curseforge(query, limit=10):
    """Поиск модов на CurseForge по строковому запросу."""
    try:
        headers = {
            'x-api-key': config.CURSEFORGE_API_KEY,
            'Accept': 'application/json'
        }
        # gameId 432 - Minecraft
        # classId 6 - Mods
        search_url = f"https://api.curseforge.com/v1/mods/search?gameId=432&classId=6&searchFilter={query}&pageSize={limit}"
        resp = requests.get(search_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get('data', [])
            results = []
            for mod in data:
                results.append({
                    'id': mod.get('id'),
                    'title': mod.get('name'),
                    'summary': mod.get('summary'),
                    'logo': mod.get('logo', {}).get('url'),
                    'url': mod.get('links', {}).get('websiteUrl'),
                    'downloads': mod.get('downloadCount'),
                    'version': mod.get('latestFiles', [{}])[0].get('displayName', 'N/A')
                })
            return results
    except Exception as e:
        print(f"CurseForge Search Error: {e}")
    return []

def get_curseforge_mod_by_id(mod_id):
    """Получение детальных данных мода по ID."""
    try:
        headers = {
            'x-api-key': config.CURSEFORGE_API_KEY,
            'Accept': 'application/json'
        }
        url = f"https://api.curseforge.com/v1/mods/{mod_id}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            mod = resp.json().get('data', {})
            return {
                'title': mod.get('name'),
                'summary': mod.get('summary'),
                'version': mod.get('latestFiles', [{}])[0].get('displayName', 'N/A'),
                'downloads': mod.get('downloadCount'),
                'url': mod.get('links', {}).get('websiteUrl'),
                'logo': mod.get('logo', {}).get('url'),
                'source': 'CurseForge'
            }
    except Exception as e:
        print(f"CurseForge Get ID Error: {e}")
    return None
