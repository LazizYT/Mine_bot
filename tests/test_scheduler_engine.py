"""Тесты Scheduler Engine (scheduler_engine.py)."""
import unittest
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_base  # noqa: F401

import scheduler_engine as se
import channel_manager as cm
import content_storage as cs
import database


class TestSchedulerEngine(unittest.TestCase):

    def setUp(self):
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM post_tags")
        cur.execute("DELETE FROM posts")
        cur.execute("DELETE FROM queue")
        cur.execute("DELETE FROM schedules")
        cur.execute("DELETE FROM publications")
        cur.execute("DELETE FROM publication_logs")
        cur.execute("DELETE FROM system_events")
        cur.execute("DELETE FROM audit_log")
        cur.execute("DELETE FROM channel_settings")
        cur.execute("DELETE FROM managed_channels")
        conn.commit()
        conn.close()
        se.set_test_mode(False)

    def test_test_mode_flag(self):
        self.assertFalse(se.test_mode_enabled())
        se.set_test_mode(True)
        self.assertTrue(se.test_mode_enabled())
        se.set_test_mode(False)

    def test_parse_interval(self):
        self.assertEqual(se._parse_interval(6), 6.0)
        self.assertEqual(se._parse_interval('6h'), 6.0)
        self.assertEqual(se._parse_interval('30m'), 0.5)
        self.assertEqual(se._parse_interval(''), None)

    def test_compute_next_run_interval(self):
        now = int(time.time())
        settings = {'active': 1, 'auto_publish': 1, 'interval_hours': 6, 'cron': '', 'timezone': 'Asia/Tashkent'}
        nxt = se.compute_next_run(settings, last_run_at=now - 600)
        # последний запуск 10 минут назад, интервал 6ч => следующий через 5ч50м
        self.assertAlmostEqual(nxt, now - 600 + 6 * 3600, delta=10)
        # неактивный канал -> None
        settings['active'] = 0
        self.assertIsNone(se.compute_next_run(settings, now - 600))

    def test_compute_next_run_cron(self):
        settings = {'active': 1, 'auto_publish': 1, 'interval_hours': 6, 'cron': '0 12 * * *', 'timezone': 'Asia/Tashkent'}
        nxt = se.compute_next_run(settings, None)
        self.assertIsNotNone(nxt)
        # cron должна сработать только в полдень
        import pytz
        from datetime import datetime
        tz = pytz.timezone('Asia/Tashkent')
        dt = datetime.fromtimestamp(nxt, tz)
        self.assertEqual(dt.hour, 12)
        self.assertEqual(dt.minute, 0)

    def test_add_to_storage_and_queue(self):
        pid, qid = se.add_to_storage_and_queue(
            text="Scheduled via engine", media="", media_type="text",
            channel_id=1, channel_username="@lazikosmods",
            scheduled_time=int(time.time()) + 3600, category="Mods", tags="sodium",
            language="ru", source="telegram", priority=5)
        self.assertIsNotNone(pid)
        self.assertIsNotNone(qid)
        post = cs.get_post(pid)
        self.assertEqual(post['status'], 'scheduled')
        # проверяем, что связь queue -> post есть
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT post_id FROM queue WHERE id = ?", (qid,))
        self.assertEqual(cur.fetchone()[0], pid)
        # schedule создан
        cur.execute("SELECT post_id, status FROM schedules WHERE channel_id = 1 ORDER BY id DESC LIMIT 1")
        sched = cur.fetchone()
        self.assertEqual(sched[0], pid)
        self.assertEqual(sched[1], 'pending')
        conn.close()

    def test_find_due_channels(self):
        cm.ensure_settings('@due')
        cm.save_settings('@due', {'active': 1, 'auto_publish': 1, 'interval_hours': 1})
        # создадим публикацию в прошлом, чтобы канал был due
        due = se.find_due_channels()
        # без публикаций канал первый раз due через ~60 сек, сейчас не должен быть due
        self.assertEqual(due, [])
        # записываем успешную публикацию в прошлом
        pid, _ = cs.create_post(text="x", status='available')
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM managed_channels WHERE username = ?", ('@due',))
        cid = cur.fetchone()[0]
        cur.execute("""INSERT INTO publications (post_id, channel_id, status, scheduled_at, published_at, retry_count, message_id, created_at)
                       VALUES (?, ?, 'SUCCESS', ?, ?, 0, '', ?)""", (pid, cid, int(time.time()) - 7200, int(time.time()) - 7200, int(time.time())))
        conn.commit()
        conn.close()
        due = se.find_due_channels()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]['username'], '@due')

    def test_select_best_post(self):
        pid, _ = cs.create_post(text="Select me", status='available')
        settings = se.build_channel_settings(1, '@lazikosmods')
        chosen = se.select_best_post(1, '@lazikosmods', settings)
        self.assertEqual(chosen, pid)

    def test_run_scheduler_dry_run(self):
        cm.ensure_settings('@dry')
        cm.save_settings('@dry', {'active': 1, 'auto_publish': 1, 'interval_hours': 1})
        cs.create_post(text="Dry run post", status='available')
        report = se.run_scheduler(None, dry_run=True)
        # канал ещё не due (нет публикаций, первый запуск +60с) => due может быть 0
        self.assertIn('due', report)
        self.assertIn('selected', report)
        self.assertIn('skipped', report)
        self.assertIn('reasons', report)

    def test_log_publication_and_history(self):
        pid, _ = cs.create_post(text="pub", status='available')
        cm.ensure_settings('@hist')
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM managed_channels WHERE username = ?", ('@hist',))
        cid = cur.fetchone()[0]
        conn.close()
        se.log_publication(pid, cid, None, int(time.time()), 'SUCCESS')
        hist = se.publication_history(status='SUCCESS')
        self.assertEqual(hist['total'], 1)
        self.assertEqual(hist['items'][0]['post_id'], pid)

    def test_analytics(self):
        pid, _ = cs.create_post(text="a", status='published')
        cm.ensure_settings('@an')
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM managed_channels WHERE username = ?", ('@an',))
        cid = cur.fetchone()[0]
        conn.close()
        se.log_publication(pid, cid, None, int(time.time()), 'SUCCESS')
        a = se.analytics()
        self.assertEqual(a['posts']['total'], 1)
        self.assertEqual(a['posts']['published'], 1)
        self.assertEqual(a['publications']['success'], 1)

    def test_log_event(self):
        se.log_event('test_event', 'hello world')
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("SELECT event_type, message FROM system_events WHERE event_type = 'test_event'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[1], 'hello world')


if __name__ == '__main__':
    unittest.main()
