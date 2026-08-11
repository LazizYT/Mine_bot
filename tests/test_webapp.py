"""Тесты Web API платформы (webapp.py /api/platform/*) и аудита."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_base  # noqa: F401

import webapp
import database


class TestPlatformAPI(unittest.TestCase):

    def setUp(self):
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM post_tags")
        cur.execute("DELETE FROM posts")
        cur.execute("DELETE FROM queue")
        cur.execute("DELETE FROM schedules")
        cur.execute("DELETE FROM publications")
        cur.execute("DELETE FROM system_events")
        cur.execute("DELETE FROM audit_log")
        cur.execute("DELETE FROM templates")
        cur.execute("DELETE FROM network_channels")
        cur.execute("DELETE FROM networks")
        cur.execute("DELETE FROM channel_settings")
        cur.execute("DELETE FROM managed_channels")
        cur.execute("DELETE FROM userbot_sources")
        cur.execute("DELETE FROM userbot_history")
        conn.commit()
        conn.close()
        self.client = webapp.app.test_client()

    def test_platform_page(self):
        r = self.client.get('/platform')
        self.assertEqual(r.status_code, 200)

    def test_posts_crud(self):
        r = self.client.post('/api/platform/posts', json={'text': 'API post', 'category': 'Mods', 'language': 'ru'})
        self.assertEqual(r.status_code, 200)
        pid = r.get_json()['post_id']
        r = self.client.get('/api/platform/posts/' + str(pid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['item']['text'], 'API post')
        r = self.client.put('/api/platform/posts/' + str(pid), json={'status': 'queued', 'priority': 7})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/platform/posts/' + str(pid))
        self.assertEqual(r.get_json()['item']['status'], 'queued')
        r = self.client.delete('/api/platform/posts/' + str(pid))
        self.assertEqual(r.status_code, 200)

    def test_posts_list_and_dup(self):
        self.client.post('/api/platform/posts', json={'text': 'dup', 'category': 'Mods'})
        r = self.client.get('/api/platform/posts')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['total'], 1)
        r = self.client.post('/api/platform/posts', json={'text': 'dup', 'category': 'Mods'})
        self.assertEqual(r.status_code, 400)

    def test_post_actions(self):
        r = self.client.post('/api/platform/posts', json={'text': 'actions'})
        pid = r.get_json()['post_id']
        self.assertEqual(self.client.post('/api/platform/posts/' + str(pid) + '/archive').status_code, 200)
        self.assertEqual(self.client.post('/api/platform/posts/' + str(pid) + '/restore').status_code, 200)
        r = self.client.post('/api/platform/posts/' + str(pid) + '/duplicate')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.get_json()['post_id'])

    def test_storage_stats(self):
        self.client.post('/api/platform/posts', json={'text': 'stat'})
        r = self.client.get('/api/platform/storage/stats')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['stats']['total'], 1)

    def test_channels(self):
        r = self.client.get('/api/platform/channels')
        self.assertEqual(r.status_code, 200)
        r = self.client.put('/api/platform/channels/@test', json={'interval_hours': 9})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/platform/channels/@test')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['item']['interval_hours'], 9)

    def test_networks(self):
        r = self.client.post('/api/platform/networks', json={'name': 'N', 'channels': ['@lazikomods']})
        self.assertEqual(r.status_code, 200)
        nid = r.get_json()['network_id']
        r = self.client.get('/api/platform/networks')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['items']), 1)
        r = self.client.post('/api/platform/networks/' + str(nid) + '/channels', json={'username': '@x', 'action': 'add'})
        self.assertEqual(r.status_code, 200)
        r = self.client.post('/api/platform/networks/' + str(nid) + '/clone', json={'name': 'C'})
        self.assertEqual(r.status_code, 200)
        r = self.client.delete('/api/platform/networks/' + str(nid))
        self.assertEqual(r.status_code, 200)

    def test_templates(self):
        r = self.client.post('/api/platform/templates', json={'name': 'T', 'data': {'interval_hours': 4}})
        self.assertEqual(r.status_code, 200)
        tid = r.get_json()['template_id']
        r = self.client.get('/api/platform/templates')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['items']), 1)
        r = self.client.delete('/api/platform/templates/' + str(tid))
        self.assertEqual(r.status_code, 200)

    def test_scheduler(self):
        r = self.client.post('/api/platform/scheduler/test-mode', json={'enabled': True})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['test_mode'])
        r = self.client.post('/api/platform/scheduler/test-mode', json={'enabled': False})
        self.assertTrue(not r.get_json()['test_mode'])
        r = self.client.post('/api/platform/scheduler/run', json={'dry_run': True})
        self.assertEqual(r.status_code, 200)
        self.assertIn('report', r.get_json())

    def test_publications(self):
        r = self.client.get('/api/platform/publications')
        self.assertEqual(r.status_code, 200)
        self.assertIn('total', r.get_json())
        r = self.client.post('/api/platform/publications/retry')
        self.assertEqual(r.status_code, 200)

    def test_analytics(self):
        r = self.client.get('/api/platform/analytics')
        self.assertEqual(r.status_code, 200)
        self.assertIn('analytics', r.get_json())

    def test_events(self):
        r = self.client.get('/api/platform/events')
        self.assertEqual(r.status_code, 200)
        self.assertIn('items', r.get_json())

    def test_calendar(self):
        r = self.client.get('/api/platform/calendar')
        self.assertEqual(r.status_code, 200)
        self.assertIn('items', r.get_json())

    def test_settings(self):
        r = self.client.get('/api/platform/settings')
        self.assertEqual(r.status_code, 200)
        r = self.client.put('/api/platform/settings', json={'notifications_enabled': '1'})
        self.assertEqual(r.status_code, 200)

    def test_audit(self):
        self.client.post('/api/platform/posts', json={'text': 'audit me'})
        r = self.client.get('/api/platform/audit')
        self.assertEqual(r.status_code, 200)
        items = r.get_json()['items']
        self.assertTrue(any(i['action'] == 'post_create' for i in items))
        r = self.client.get('/api/platform/audit?action=post_create')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(len(r.get_json()['items']) >= 1)

    def test_audit_log_function(self):
        database.audit_log('test_action', 'target123', old_value='a', new_value='b')
        rows = database.get_audit_log()
        self.assertEqual(rows[0]['action'], 'test_action')
        self.assertEqual(rows[0]['target'], 'target123')
        self.assertEqual(rows[0]['old_value'], 'a')
        self.assertEqual(rows[0]['new_value'], 'b')
        rows_filtered = database.get_audit_log(action='test_action')
        self.assertEqual(len(rows_filtered), 1)

    def test_audit_pagination(self):
        for i in range(5):
            database.audit_log('bulk_test', f"item:{i}")
        r = self.client.get('/api/platform/audit?page=1&per_page=2')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(len(d['items']), 2)
        self.assertEqual(d['total'], 5)
        self.assertGreaterEqual(d['pages'], 3)
        r = self.client.get('/api/platform/audit?page=3&per_page=2')
        self.assertEqual(len(r.get_json()['items']), 1)
        r = self.client.get('/api/platform/audit?action=bulk_test&page=1&per_page=10')
        self.assertEqual(r.get_json()['total'], 5)

    def test_userbot_status(self):
        r = self.client.get('/api/platform/userbot/status')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn('enabled', d)
        self.assertIn('configured', d)

    def test_userbot_sources_crud(self):
        r = self.client.post('/api/platform/userbot/sources', json={'username': '@src_channel'})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/platform/userbot/sources')
        self.assertEqual(r.status_code, 200)
        items = r.get_json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['username'], '@src_channel')
        r = self.client.post('/api/platform/userbot/sources/' + '@src_channel' + '/toggle', json={'enabled': 0})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/platform/userbot/sources')
        self.assertEqual(r.get_json()['items'][0]['enabled'], 0)
        r = self.client.delete('/api/platform/userbot/sources/' + '@src_channel')
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/platform/userbot/sources')
        self.assertEqual(len(r.get_json()['items']), 0)

    def test_userbot_history_api(self):
        database.userbot_history_add('@src_channel', 100, 'grp1', post_id=5, status='captured')
        r = self.client.get('/api/platform/userbot/history')
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn('items', d)
        self.assertEqual(len(d['items']), 1)
        self.assertEqual(d['items'][0]['message_id'], 100)

    def test_publisher_storage_helpers(self):
        import publisher
        self.assertEqual(publisher._parse_st_ref('st:-100123:42'), (-100123, 42))
        self.assertIsNone(publisher._parse_st_ref('photo.jpg'))
        self.assertTrue(publisher._is_storage_media('st:-100:1,st:-100:2'))
        self.assertFalse(publisher._is_storage_media('st:-100:1,photo.jpg'))
        photos, docs = publisher._split_media('st:-100:1,doc:file.jar')
        self.assertEqual(photos, ['st:-100:1'])
        self.assertEqual(docs, ['file.jar'])

    def test_userbot_relay_marker(self):
        import handlers
        clean, src = handlers._extract_ub_marker("Some text\n\n__UBR__:https://t.me/ch/5")
        self.assertEqual(clean, "Some text")
        self.assertEqual(src, "https://t.me/ch/5")
        clean, src = handlers._extract_ub_marker("Plain caption")
        self.assertEqual(clean, "Plain caption")
        self.assertIsNone(src)
        clean, src = handlers._extract_ub_marker("\n\n__UBR__:https://t.me/ch/9")
        self.assertEqual(clean, "")
        self.assertEqual(src, "https://t.me/ch/9")


if __name__ == '__main__':
    unittest.main()
