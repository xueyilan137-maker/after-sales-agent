"""Small synthetic lexical corpus checks, not external-case quality metrics."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from after_sales import policy as p


class PolicyTests(unittest.TestCase):
    def test_effective_start_and_no_applicable_policy(self):
        self.assertFalse(p.search_knowledge('损坏','damage','2026-09-30')['active_policy'])
        self.assertTrue(p.search_knowledge('损坏','damage','2026-10-01')['active_policy'])
        self.assertEqual('1.0.0',p.load_policy('damage','2026-10-13')['version'])

    def test_expected_relevance_and_exact_citations(self):
        for query, kind, expected in [('审批有效期','damage','DAMAGE-04'),
                                      ('物流运输超过72小时','logistics','LOGISTICS-01')]:
            result=p.search_knowledge(query,kind,'2026-10-12',5)
            self.assertIn(expected,[m['clause_id'] for m in result['matches']])
            policy=p.load_policy(kind,'2026-10-12')
            for match in result['matches']:
                ref=match['citation']
                self.assertEqual(policy['content_sha256'],ref['content_sha256'])
                self.assertEqual('1.0.0',ref['version'])
                self.assertTrue(ref['source'].endswith('#'+match['clause_id']))
                self.assertEqual(next(c['text'] for c in policy['chunks'] if c['clause_id']==match['clause_id']),match['text'])

    def test_unrelated_query_and_invalid_input(self):
        result=p.search_knowledge('zxqv987654','damage','2026-10-12')
        self.assertEqual([],result['matches'])
        self.assertEqual([],result['cases'])
        for query,top_k in [('',3),('x'*501,3),('损坏',0),('损坏',6)]:
            with self.assertRaises(ValueError):p.search_policy(query,top_k)
        with self.assertRaises(ValueError):p.load_policy('unknown')

    def test_examples_are_illustrations_not_execution_evidence(self):
        result=p.search_knowledge('超过七天损坏申报','damage','2026-10-12',5)
        self.assertTrue(result['cases'])
        self.assertTrue(all(c['data_kind']=='synthetic_design_example' and c['authority']=='illustration_only_not_execution_evidence' for c in result['cases']))
        self.assertTrue(all(c['case_kind']=='damage' for c in result['cases']))

    def test_isolated_version_switch_and_conflict_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='after-sales-policy-') as root:
            directory=Path(root)
            first=p._read_policy('policies.json')
            document=first.pop('text')
            first.pop('chunks'); first.pop('content_sha256')
            first['effective_until']='2026-10-12'
            second={**first,'version':'2.0.0','effective_from':'2026-10-13','effective_until':None}
            (directory/first['document']).write_text(document,encoding='utf-8')
            for filename,policy in [('first.json',first),('second.json',second)]:
                (directory/filename).write_text(json.dumps(policy),encoding='utf-8')
            with patch.object(p,'DATA_DIR',directory),patch.dict(p.MANIFESTS,{'damage':['first.json','second.json']}):
                self.assertEqual('1.0.0',p.load_policy('damage','2026-10-12')['version'])
                self.assertEqual('2.0.0',p.load_policy('damage','2026-10-13')['version'])
                self.assertEqual('1.0.0',p.load_policy('damage',policy_id=first['policy_id'],version='1.0.0')['version'])
                second['effective_from']='2026-10-12'
                (directory/'second.json').write_text(json.dumps(second),encoding='utf-8')
                result=p.search_policy('损坏',as_of='2026-10-12')
                self.assertFalse(result['active_policy'])
                self.assertEqual([],result['matches'])
