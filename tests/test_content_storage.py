"""Тесты Content Storage (content_storage.py)."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_base  # noqa: F401  (устанавливает DB_PATH и init_db)

import content_storage as cs
import database


class TestContentStorage(unittest.TestCase):

    def setUp(self):
        # очищаем таблицы постов между тестами
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM post_tags")
        cur.execute("DELETE FROM posts")
        conn.commit()
        conn.close()

    def test_create_and_get_post(self):
        pid, dup = cs.create_post(text="Test post", category="Mods", language="ru", source="manual")
        self.assertIsNotNone(pid)
        self.assertIsNone(dup)
        p = cs.get_post(pid)
        self.assertEqual(p['text'], "Test post")
        self.assertEqual(p['status'], 'available')
        self.assertEqual(p['category'], 'Mods')

    def test_duplicate_detection(self):
        pid1, _ = cs.create_post(text="Same text content", media="")
        pid2, dup = cs.create_post(text="Same text content", media="")
        self.assertIsNone(pid2)
        self.assertTrue(dup)
        self.assertNotEqual(pid1, pid2 if pid2 else -1)

    def test_update_post(self):
        pid, _ = cs.create_post(text="Original", category="Mods")
        cs.update_post(pid, text="Updated", priority=9, status='queued')
        p = cs.get_post(pid)
        self.assertEqual(p['text'], 'Updated')
        self.assertEqual(p['priority'], 9)
        self.assertEqual(p['status'], 'queued')

    def test_archive_restore(self):
        pid, _ = cs.create_post(text="Archive me")
        cs.archive_post(pid)
        self.assertEqual(cs.get_post(pid)['status'], 'archived')
        cs.restore_post(pid)
        self.assertEqual(cs.get_post(pid)['status'], 'available')

    def test_duplicate_post(self):
        pid, _ = cs.create_post(text="Copy me", category="Shaders", tags="shader,fancy")
        new_id = cs.duplicate_post(pid)
        self.assertIsNotNone(new_id)
        p = cs.get_post(new_id)
        self.assertEqual(p['text'], "Copy me")
        self.assertEqual(p['status'], 'draft')
        self.assertEqual(p['category'], 'Shaders')

    def test_list_posts_filters(self):
        cs.create_post(text="A1", category="Mods", language="uz", source="modrinth")
        cs.create_post(text="A2", category="Shaders", language="ru", source="telegram")
        cs.create_post(text="A3", category="Mods", language="ru", source="manual", status='queued')
        data = cs.list_posts(category="Mods")
        self.assertEqual(data['total'], 2)
        data2 = cs.list_posts(language="ru")
        self.assertEqual(data2['total'], 2)
        data3 = cs.list_posts(status='queued')
        self.assertEqual(data3['total'], 1)
        data4 = cs.list_posts(search="A2")
        self.assertEqual(data4['total'], 1)

    def test_tags_sync(self):
        pid, _ = cs.create_post(text="Tagged post", tags="a,b,c")
        tags = cs.get_post_tags(pid)
        self.assertEqual(sorted(tags), ['a', 'b', 'c'])

    def test_mark_used_and_reuse(self):
        pid, _ = cs.create_post(text="Reuse check", status='available')
        settings = {'reuse_mode': 'never', '_published_channels_map': {}}
        post = cs.get_post(pid)
        self.assertTrue(cs.check_reuse(post, 1, settings))
        cs.mark_used(pid, '@lazikomods')
        p = cs.get_post(pid)
        self.assertIn('@lazikomods', p['published_channels'])
        self.assertEqual(p['usage_count'], 1)

    def test_select_post_fifo(self):
        p1, _ = cs.create_post(text="First", status='available')
        p2, _ = cs.create_post(text="Second", status='available')
        settings = {'selection': 'fifo', 'reuse_mode': 'unlimited', 'languages': '', 'sources': '', 'categories': ''}
        chosen = cs.select_post(1, settings)
        self.assertEqual(chosen, p1)
        settings['selection'] = 'lifo'
        chosen2 = cs.select_post(1, settings)
        self.assertEqual(chosen2, p2)

    def test_delete_post(self):
        pid, _ = cs.create_post(text="Delete me")
        cs.delete_post(pid)
        self.assertIsNone(cs.get_post(pid))

    def test_storage_stats(self):
        cs.create_post(text="S1", status='available')
        cs.create_post(text="S2", status='published')
        cs.create_post(text="S3", status='archived')
        stats = cs.storage_stats()
        self.assertEqual(stats['total'], 3)
        self.assertEqual(stats['available'], 1)
        self.assertEqual(stats['published'], 1)
        self.assertEqual(stats['archived'], 1)


if __name__ == '__main__':
    unittest.main()
