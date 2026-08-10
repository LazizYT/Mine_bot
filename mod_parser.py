import requests

def parse_mod_data(url):
    """
    Определяет тип ссылки и извлекает данные.
    Поддерживает Modrinth.
    """
    if "modrinth.com" in url:
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
