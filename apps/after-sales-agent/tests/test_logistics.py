"""Isolated logistics transactions; administrator identities are simulated."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import sitecustomize
from after_sales import store as s


class LogisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='after-sales-logistics-')
        self.env=patch.dict(os.environ,{'AFTER_SALES_DATA_DIR':self.temp.name})
        self.env.start(); s.init_store()
        self.owner='isolated-logistics-owner'

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def report(self,scenario='shipping-stalled'):
        order=s.create_demo_run(self.owner,scenario)['order']
        return s.save_logistics_report(self.owner,order['order_id'],'合成物流异常','合成客户陈述')

    def error(self,code,fn,*args):
        with self.assertRaises(s.BusinessError) as caught:fn(*args)
        self.assertEqual(code,caught.exception.code)

    def approved(self,ticket):
        proposal=s.propose_resolution(self.owner,ticket['ticket_id'])['proposals'][0]
        s.review_proposal(self.owner,proposal['proposal_id'],proposal['digest'],'approve','模拟管理员',True)
        return proposal

    def test_inquiry_waits_for_followup_and_preserves_events(self):
        ticket=self.report()
        events=s.get_shipping_events(self.owner,ticket['order_id'])
        proposal=self.approved(ticket)
        result=s.execute_resolution(self.owner,proposal['proposal_id'])
        self.assertEqual('carrier_inquiry',result['resolution'])
        self.assertEqual('none',result['external_effect'])
        waiting=s.get_ticket(self.owner,ticket['ticket_id'])
        self.assertEqual('awaiting_followup',waiting['status'])
        self.assertEqual([],waiting['followups'])
        final=s.record_shipping_followup(self.owner,ticket['ticket_id'],'delivered','管理员记录合成送达结果',waiting['revision'])
        self.assertEqual('resolved',final['status'])
        self.assertEqual(events,s.get_shipping_events(self.owner,ticket['order_id']))
        self.assertEqual(ticket['reported_at'],final['reported_at'])
        self.assertEqual(ticket['business_reported_at'],final['business_reported_at'])
        self.assertEqual(1,len(final['operations']))

    def test_signed_delivery_conflict_never_proposes_fulfillment(self):
        ticket=self.report('shipping-disputed')
        result=s.propose_resolution(self.owner,ticket['ticket_id'])
        self.assertEqual('manual_review',result['status'])
        self.assertEqual([],result['proposals'])
        self.assertEqual([],result['operations'])
        self.assertTrue(any('签收' in reason for reason in result['reasons']))

    def test_followup_requires_execution_and_current_revision(self):
        ticket=self.report()
        self.error('FOLLOWUP_NOT_PENDING',s.record_shipping_followup,self.owner,ticket['ticket_id'],'delivered','过早跟进',ticket['revision'])
        proposal=self.approved(ticket)
        s.execute_resolution(self.owner,proposal['proposal_id'])
        self.error('REVISION_CONFLICT',s.record_shipping_followup,self.owner,ticket['ticket_id'],'manual_review','合成',ticket['revision']+1)
        self.error('TICKET_NOT_FOUND',s.record_shipping_followup,'other-owner',ticket['ticket_id'],'delivered','合成',ticket['revision'])

    def test_concurrent_followup_is_single_and_cannot_be_overwritten(self):
        ticket=self.report(); proposal=self.approved(ticket)
        s.execute_resolution(self.owner,proposal['proposal_id'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:s.record_shipping_followup(self.owner,ticket['ticket_id'],'manual_review','同一合成跟进',ticket['revision']),range(4)))
        self.assertTrue(all(r['status']=='manual_review' and len(r['followups'])==1 for r in results))
        self.error('FOLLOWUP_ALREADY_RECORDED',s.record_shipping_followup,self.owner,ticket['ticket_id'],'delivered','不能覆盖',ticket['revision']+1)
