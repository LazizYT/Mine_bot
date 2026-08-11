"""Тесты Channel Manager (channel_manager.py)."""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_base  # noqa: F401

import channel_manager as cm
import database


class TestChannelManager(unittest.TestCase):

    def setUp(self):
        conn = database._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM network_channels")
        cur.execute("DELETE FROM networks")
        cur.execute("DELETE FROM templates")
        cur.execute("DELETE FROM channel_settings")
        cur.execute("DELETE FROM managed_channels")
        conn.commit()
        conn.close()

    def test_ensure_and_get_settings(self):
        s = cm.ensure_settings('@ch1')
        self.assertEqual(s['username'], '@ch1')
        self.assertEqual(s['selection'], 'random')
        self.assertEqual(s['interval_hours'], 6)

    def test_save_settings(self):
        cm.ensure_settings('@ch1')
        cm.save_settings('@ch1', {'interval_hours': 12, 'selection': 'fifo', 'reuse_mode': 'unlimited'})
        s = cm.get_settings('@ch1')
        self.assertEqual(s['interval_hours'], 12)
        self.assertEqual(s['selection'], 'fifo')
        self.assertEqual(s['reuse_mode'], 'unlimited')

    def test_get_settings_missing(self):
        self.assertIsNone(cm.get_settings('@nope'))

    def test_get_all_channel_settings(self):
        cm.ensure_settings('@a')
        cm.ensure_settings('@b')
        rows = cm.get_all_channel_settings()
        self.assertEqual(len(rows), 2)

    def test_channel_table(self):
        cm.ensure_settings('@a')
        rows = cm.channel_table()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['username'], '@a')
        self.assertEqual(rows[0]['status'], 'ACTIVE')
        self.assertIn('reuse_mode', rows[0])
        self.assertIn('reuse_days', rows[0])

    def test_networks_crud(self):
        nid = cm.create_network("Net", "desc")
        self.assertIsNotNone(nid)
        cm.add_channel_to_network(nid, '@ch1')
        channels = cm.network_channels(nid)
        self.assertEqual(channels, ['@ch1'])
        self.assertFalse(cm.is_network_paused(nid))
        cm.pause_network(nid, True)
        self.assertTrue(cm.is_network_paused(nid))
        cm.rename_network(nid, "Net2")
        nets = cm.get_networks()
        self.assertEqual(nets[0]['name'], "Net2")
        cm.remove_channel_from_network(nid, '@ch1')
        self.assertEqual(cm.network_channels(nid), [])

    def test_network_delete(self):
        nid = cm.create_network("Net")
        cm.delete_network(nid)
        self.assertEqual(cm.get_networks(), [])

    def test_clone_network(self):
        nid = cm.create_network("Orig")
        cm.add_channel_to_network(nid, '@ch1')
        new_id = cm.clone_network(nid, "Clone")
        self.assertIsNotNone(new_id)
        self.assertEqual(cm.network_channels(new_id), ['@ch1'])

    def test_templates(self):
        tid = cm.create_template("Tpl", "desc", {"interval_hours": 8, "selection": "weighted"})
        templates = cm.get_templates()
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]['data']['interval_hours'], 8)
        cm.ensure_settings('@t1')
        count = cm.apply_template(tid, ['@t1'])
        self.assertEqual(count, 1)
        self.assertEqual(cm.get_settings('@t1')['selection'], 'weighted')

    def test_bulk_update(self):
        cm.ensure_settings('@b1')
        cm.ensure_settings('@b2')
        count = cm.bulk_update(['@b1', '@b2'], {'interval_hours': 3})
        self.assertEqual(count, 2)
        self.assertEqual(cm.get_settings('@b1')['interval_hours'], 3)
        self.assertEqual(cm.get_settings('@b2')['interval_hours'], 3)

    def test_clone_settings(self):
        cm.ensure_settings('@src')
        cm.save_settings('@src', {'interval_hours': 5, 'selection': 'smart'})
        count = cm.clone_settings('@src', ['@dst1', '@dst2'])
        self.assertEqual(count, 2)
        self.assertEqual(cm.get_settings('@dst1')['interval_hours'], 5)
        self.assertEqual(cm.get_settings('@dst2')['selection'], 'smart')

    def test_delete_channel(self):
        cm.ensure_settings('@del')
        cm.delete_channel('@del')
        self.assertIsNone(cm.get_settings('@del'))


if __name__ == '__main__':
    unittest.main()
