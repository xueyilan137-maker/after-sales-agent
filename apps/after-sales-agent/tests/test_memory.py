"""Pinned DeerMem persistence/CRUD in isolated roots with remote sockets denied."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import sitecustomize
from after_sales import customer_memory as m, store as s


class MemoryTests(unittest.TestCase):
    def setUp(self):
        m.close_memory()
        self.temp = tempfile.TemporaryDirectory(prefix='after-sales-memory-')
        self.env = patch.dict(os.environ, {'AFTER_SALES_DATA_DIR': self.temp.name})
        self.env.start()
        s.init_store()

    def tearDown(self):
        m.close_memory()
        self.env.stop()
        self.temp.cleanup()

    def error(self, code, fn, *args):
        with self.assertRaises(s.BusinessError) as caught:
            fn(*args)
        self.assertEqual(code, caught.exception.code)

    def test_persist_correct_forget_and_owner_isolation(self):
        first = m.save_preference('owner-a', 'resolution_preference', 'reship', '合成确认')['preferences'][0]
        m.close_memory()
        self.assertEqual(first, m.get_customer_memory('owner-a')['preferences'][0])
        self.assertEqual([], m.get_customer_memory('owner-b')['preferences'])
        self.error('MEMORY_CONFLICT', m.save_preference, 'owner-a', 'resolution_preference', 'refund', '纠正', '0'*64)
        second = m.save_preference('owner-a', 'resolution_preference', 'refund', '纠正', first['digest'])['preferences'][0]
        self.assertEqual(first['fact_id'], second['fact_id'])
        self.assertEqual(2, second['revision'])
        self.assertEqual(first['digest'], second['previous_digest'])
        self.error('MEMORY_CONFLICT', m.forget_preference, 'owner-a', second['fact_id'], first['digest'])
        m.forget_preference('owner-b', second['fact_id'], second['digest'])
        self.assertEqual(second, m.get_customer_memory('owner-a')['preferences'][0])
        self.assertEqual([], m.forget_preference('owner-a', second['fact_id'], second['digest'])['preferences'])
        m.close_memory()
        self.assertEqual([], m.get_customer_memory('owner-a')['preferences'])
        self.error('MEMORY_CONFLICT', m.save_preference, 'owner-a', 'resolution_preference', 'reship', '旧页面', second['digest'])

    def test_concurrent_creation_and_repeat_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: m.save_preference('owner-a','language','zh-CN','相同合成确认'), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(1, len(results[0]['preferences']))
        self.assertEqual(1, results[0]['preferences'][0]['revision'])

    def test_preference_does_not_supply_current_choice_or_approval(self):
        m.save_preference('owner-a','resolution_preference','refund','长期倾向')
        order = s.create_demo_run('owner-a','damage-in-window')['order']
        ticket = s.save_damage_report('owner-a',order['order_id'],'合成裂纹','合成文字陈述',None)
        blocked = s.propose_resolution('owner-a',ticket['ticket_id'])
        self.assertIn('requested_resolution', blocked['missing_fields'])
        ticket = s.save_damage_report('owner-a',order['order_id'],None,None,'reship',ticket['revision'])
        proposal = s.propose_resolution('owner-a',ticket['ticket_id'])['proposals'][0]
        self.assertEqual('reship',proposal['payload']['resolution'])
        self.error('HUMAN_APPROVAL_REQUIRED',s.execute_resolution,'owner-a',proposal['proposal_id'])

    def test_invalid_and_failed_read_have_no_remote_fallback(self):
        self.error('INVALID_MEMORY',m.save_preference,'owner-a','order_status','resolved','不允许的业务事实')
        self.error('INVALID_MEMORY',m.save_preference,'owner-a','language','zh-CN',' ')
        with patch.object(m,'manager',side_effect=RuntimeError('backend unavailable')):
            self.error('MEMORY_UNAVAILABLE',m.get_customer_memory,'owner-a')

    def test_write_ack_without_readback_is_rejected(self):
        backend = m.manager()
        with patch.object(type(backend),'create_fact',return_value=({},'unpersisted-id')):
            self.error('MEMORY_WRITE_UNAVAILABLE',m.save_preference,'owner-a','language','zh-CN','合成确认')
        self.assertEqual([],m.get_customer_memory('owner-a')['preferences'])
