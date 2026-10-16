"""Historical projections are pointers, never current approval or lost history."""
import copy
import json
import unittest

import sitecustomize
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from after_sales.plugin import AfterSalesMiddleware


NAME = 'after-sales-demo_get_after_sales_ticket'


def history(payload=None, **kwargs):
    payload = payload or {'data_kind': 'synthetic_demo_data', 'ticket_id': 'TKT-FIXTURE',
        'order_id': 'DEMO-FIXTURE', 'status': 'approved', 'revision': 1,
        'reported_at': '2026-10-13T08:52:30Z', 'business_reported_at': '2026-10-12',
        'known_information': {'evidence_note': '原始合成证据' * 300},
        'proposal': {'proposal_id': 'PRP-OLD', 'status': 'approved',
            'citations': [{'policy_id': 'damage-demo-v1', 'version': '1.0.0', 'clause_id': 'DAMAGE-01', 'sha256': 'source-hash'}],
            'policy_basis': [{'text': '政策全文' * 100}]}}
    return [HumanMessage(content='完整用户申报，不可删除'),
        AIMessage(content='', tool_calls=[{'name': NAME, 'id': 'old', 'args': {'ticket_id': 'TKT-FIXTURE'}}]),
        ToolMessage(name=NAME, tool_call_id='old', content=json.dumps(payload, ensure_ascii=False), **kwargs),
        HumanMessage(content='证据已更改，请查询最新工单')]


class HistoricalContextTests(unittest.TestCase):
    def test_large_historical_snapshot_is_explicit_pointer(self):
        messages = history()
        before = copy.deepcopy([m.model_dump() for m in messages])
        result = AfterSalesMiddleware.compact_model_messages(messages)
        payload = json.loads(result[2].content)
        self.assertTrue(payload['historical_result_omitted'])
        self.assertFalse(payload['authorizes_current_action'])
        self.assertEqual('TKT-FIXTURE', payload['ticket_id'])
        self.assertEqual('PRP-OLD', payload['proposal']['proposal_id'])
        self.assertEqual('approved', payload['status'])
        self.assertEqual(1, payload['revision'])
        self.assertIn('known_information', payload['omitted_fields'])
        self.assertEqual(64, len(payload['original_content_sha256']))
        self.assertEqual(json.loads(messages[2].content)['proposal']['citations'], payload['proposal']['citations'])
        self.assertLess(len(result[2].content), len(messages[2].content) // 2)
        self.assertEqual(before, [m.model_dump() for m in messages])
        self.assertEqual([m.tool_call_id for m in result if isinstance(m, ToolMessage)], ['old'])
        self.assertEqual(messages[0].content, result[0].content)

    def test_current_round_and_host_reminders_do_not_shift_boundary(self):
        messages = history()
        fresh = messages[2].model_copy(update={'tool_call_id': 'new'})
        messages += [AIMessage(content='', tool_calls=[{'name': NAME, 'id': 'new', 'args': {}}]), fresh,
                     HumanMessage(content='预算提醒', name='budget_warning'),
                     HumanMessage(content='日期提醒', additional_kwargs={'hide_from_ui': True})]
        result = AfterSalesMiddleware.compact_model_messages(messages)
        self.assertTrue(json.loads(result[2].content)['historical_result_omitted'])
        self.assertEqual(json.loads(fresh.content), json.loads(result[5].content))
        self.assertEqual(messages[4].tool_calls, result[4].tool_calls)
        self.assertEqual(messages[-2:], result[-2:])

    def test_errors_unknown_and_unpaired_outputs_are_not_omitted(self):
        for change in ('transport_error', 'business_error', 'unknown', 'unpaired', 'wrong_name', 'duplicate_id'):
            with self.subTest(change=change):
                messages = history()
                if change == 'transport_error':
                    messages[2].status = 'error'
                elif change == 'business_error':
                    value = json.loads(messages[2].content)
                    value['ok'] = False
                    value['error'] = {'code': 'STALE_PROPOSAL'}
                    messages[2].content = json.dumps(value)
                elif change == 'unknown':
                    value = json.loads(messages[2].content)
                    value.pop('data_kind')
                    messages[2].content = json.dumps(value)
                elif change == 'unpaired':
                    messages.pop(1)
                elif change == 'wrong_name':
                    messages[1].tool_calls[0]['name'] = 'read_file'
                else:
                    messages.insert(2, messages[1].model_copy())
                tool = next(m for m in messages if isinstance(m, ToolMessage))
                projected = next(m for m in AfterSalesMiddleware.compact_model_messages(messages) if isinstance(m, ToolMessage))
                self.assertEqual(json.loads(tool.content), json.loads(projected.content))

    def test_mixed_content_is_not_omitted(self):
        messages = history()
        messages[2].content = [{'type': 'text', 'text': messages[2].content}, {'type': 'image', 'data': 'fixture'}]
        result = AfterSalesMiddleware.compact_model_messages(messages)
        self.assertEqual(json.loads(messages[2].content[0]['text']), json.loads(result[2].content[0]['text']))
        self.assertEqual(messages[2].content[1], result[2].content[1])

    def test_projection_is_idempotent_and_metadata_preserved(self):
        messages = history(id='persisted-row', additional_kwargs={'audit': 'unchanged'})
        result = AfterSalesMiddleware.compact_model_messages(messages)
        again = AfterSalesMiddleware.compact_model_messages(result)
        self.assertEqual([m.model_dump() for m in result], [m.model_dump() for m in again])
        self.assertEqual('persisted-row', result[2].id)
        self.assertEqual({'audit': 'unchanged'}, result[2].additional_kwargs)

    def test_identical_citations_reference_a_retained_earlier_result(self):
        messages = history()
        duplicate = messages[2].model_copy(update={'tool_call_id': 'other'})
        messages[3:3] = [AIMessage(content='', tool_calls=[{'name': NAME, 'id': 'other', 'args': {}}]), duplicate]
        result = AfterSalesMiddleware.compact_model_messages(messages)
        first = json.loads(result[2].content)['proposal']
        second = json.loads(result[4].content)['proposal']
        self.assertIn('citations', first)
        self.assertNotIn('citations', second)
        self.assertEqual('old', second['citations_from_tool_call_id'])

    def test_small_result_does_not_grow_and_nonfinite_json_is_preserved(self):
        for payload in ({'data_kind': 'synthetic_demo_data', 'ticket_id': 'TKT-FIXTURE', 'known_information': {}},
                        {'data_kind': 'synthetic_demo_data', 'ticket_id': 'TKT-FIXTURE', 'revision': float('nan'),
                         'known_information': {'text': 'x' * 4000}}):
            messages = history(payload)
            result = AfterSalesMiddleware.compact_model_messages(messages)
            self.assertLessEqual(len(result[2].content), len(messages[2].content))
            self.assertNotIn('historical_result_omitted', result[2].content)


class HistoricalContextGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_rereads_changed_ticket_without_trusting_old_approval(self):
        from langchain.agents import create_agent
        from langchain_core.tools import tool
        from deerflow.config.token_budget_config import TokenBudgetConfig
        from pydantic import Field
        from test_agent_budget import LocalModel

        class RecordingModel(LocalModel):
            seen: list = Field(default_factory=list)

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self.seen.append(copy.deepcopy(messages))
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        calls = []
        fresh = {'data_kind': 'synthetic_demo_data', 'ticket_id': 'TKT-FIXTURE',
                 'status': 'manual_review', 'revision': 2, 'proposal': None,
                 'known_information': {'evidence_note': '新证据，旧审批已经失效'}}

        @tool(NAME)
        def get_ticket(ticket_id: str) -> str:
            """Local changed-ticket fixture. No MCP or business mutation."""
            calls.append(ticket_id)
            return json.dumps(fresh, ensure_ascii=False)

        model = RecordingModel(responses=[AIMessage(content='', tool_calls=[{
            'name': NAME, 'id': 'fresh', 'args': {'ticket_id': 'TKT-FIXTURE'}}],
            usage_metadata={'input_tokens': 1000, 'output_tokens': 0, 'total_tokens': 1000}),
            AIMessage(content='最新工单待人工，不执行。',
                usage_metadata={'input_tokens': 1200, 'output_tokens': 0, 'total_tokens': 1200})])
        graph = create_agent(model, [get_ticket], middleware=[AfterSalesMiddleware(
            TokenBudgetConfig(enabled=True, max_tokens=20000))], context_schema=dict)
        original = history()
        for index, item in enumerate(original):
            item.id = f'historical-row-{index}'
        before = [m.model_dump() for m in original]
        result = await graph.ainvoke({'messages': original}, config={'recursion_limit': 50},
                                    context={'run_id': 'isolated-context-graph'})
        self.assertEqual(['TKT-FIXTURE'], calls)
        self.assertEqual(2, len(model.seen))
        old = next(m for m in model.seen[0] if isinstance(m, ToolMessage))
        self.assertFalse(json.loads(old.content)['authorizes_current_action'])
        current = next(m for m in model.seen[1] if isinstance(m, ToolMessage) and m.tool_call_id == 'fresh')
        self.assertEqual(fresh, json.loads(current.content))
        saved = next(m for m in result['messages'] if isinstance(m, ToolMessage) and m.tool_call_id == 'old')
        self.assertEqual(original[2].content, saved.content)
        self.assertEqual(before, [m.model_dump() for m in original])
        self.assertEqual(2200, sum(m.usage_metadata['total_tokens'] for m in result['messages']
                                 if isinstance(m, AIMessage) and m.usage_metadata))
