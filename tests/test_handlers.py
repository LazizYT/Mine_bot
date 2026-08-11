"""Интеграционные тесты: Smart Queue -> Content Storage (handlers.py)."""
import unittest
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_base  # noqa: F401

import handlers
import scheduler_engine
import content_storage as cs
import database


class TestQueueStorageIntegration(unittest.TestCase):

    def setUp(self):
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM post_tags")
        cur.execute("DELETE FROM posts")
        cur.execute("DELETE FROM queue")
        cur.execute("DELETE FROM schedules")
        cur.execute("DELETE FROM audit_log")
        cur.execute("DELETE FROM channel_settings")
        cur.execute("DELETE FROM managed_channels")
        conn.commit()
        conn.close()

    def test_channel_id_by_username(self):
        cid = handlers._channel_id_by_username('@lazikomods')
        self.assertIsNotNone(cid)
        cid2 = handlers._channel_id_by_username('@lazikomods')
        self.assertEqual(cid, cid2)

    def test_add_to_queue_integrated_text(self):
        handlers._add_to_queue_integrated('', 'Hello from test', '', '@lazikomods', None)
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT post_id, status, channel_id, text FROM queue ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        self.assertIsNotNone(row[0], "queue should reference a post_id")
        post = cs.get_post(row[0])
        self.assertEqual(post['text'], 'Hello from test')
        self.assertEqual(post['status'], 'queued')
        self.assertEqual(post['source'], 'telegram')
        conn.close()

    def _last_post(self):
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM posts ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    def test_add_to_queue_integrated_scheduled(self):
        sched = int(time.time()) + 7200
        handlers._add_to_queue_integrated('photo123', 'Scheduled with media', '', '@lazikomods', sched)
        post_id = self._last_post()
        self.assertIsNotNone(post_id)
        post = cs.get_post(post_id)
        self.assertEqual(post['status'], 'scheduled')
        self.assertEqual(post['media'], 'photo123')
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT status FROM schedules WHERE post_id = ? ORDER BY id DESC LIMIT 1", (post_id,))
        self.assertEqual(cur.fetchone()[0], 'pending')
        conn.close()

    def test_add_to_queue_album(self):
        handlers._add_to_queue_integrated('p1,p2,p3', 'Album post', '', '@lazikomods', None)
        post_id = self._last_post()
        self.assertIsNotNone(post_id)
        post = cs.get_post(post_id)
        self.assertEqual(post['media_type'], 'album')


if __name__ == '__main__':
    unittest.main()
