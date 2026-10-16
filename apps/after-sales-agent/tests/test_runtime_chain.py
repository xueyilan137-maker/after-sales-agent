"""Pinned public lead middleware builder, fixed local messages, isolated paths.

No provider model is constructed. This is graph integration, not a live Gateway
session or actual DeepSeek evidence. Existing stdio tests cover MCP separately.
"""
import os
import json
import tempfile
import unittest
from unittest.mock import patch

import sitecustomize
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from deerflow.config import get_app_config
from deerflow.config.paths import Paths
from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.thread_state import get_thread_state_schema, normalize_middleware_state_schemas
from test_agent_budget import LocalModel, message


class RuntimeChainTests(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self, error=False, boundary=False):
        config = get_app_config()
        for feature in (config.title, config.memory, config.summarization, config.input_polish, config.suggestions):
            self.assertFalse(feature.enabled, 'A model-driven auxiliary must stay disabled')
        self.assertEqual(20000, config.token_budget.max_tokens)
        calls = []

        tool_name = 'after-sales-demo_propose_after_sales_resolution' if boundary else 'after-sales-demo_get_demo_order'
        @tool(tool_name)
        def order(order_id: str) -> str:
            """Isolated local fixture, no business/MCP mutation."""
            calls.append(order_id)
            if boundary:
                return [{'type':'text','text':json.dumps({'data_kind':'synthetic_demo_data','status':'awaiting_approval','ticket_id':'TKT-FIXTURE',
                    'proposal':{'proposal_id':'PRP-FIXTURE','status':'pending','citations':[{'policy_id':'damage-demo-v1','version':'1.0.0','clause_id':'DAMAGE-01'}]}},ensure_ascii=False,indent=2)}]
            return '{"ok":false,"error":{"code":"ORDER_NOT_FOUND"}}' if error else '{"found":true}'

        # 17k triggers the real host's budget-warning HumanMessage injection.
        # Boundary detection must inspect completed state, not request-only
        # reminders after the last ToolMessage.
        values = [17000, 1000] if error or boundary else [3224, 4674, 7686, 8381]
        responses = [message(n, i) for i, n in enumerate(values)]
        # Distinct requests avoid tripping the real loop detector fixture-wise.
        for i, response in enumerate(responses):
            response.tool_calls[0]['args']['order_id'] = f'fixture-{i}'
            response.tool_calls[0]['name'] = tool_name
        model = LocalModel(responses=responses)
        with tempfile.TemporaryDirectory(prefix='after-sales-chain-') as root, \
             patch.dict(os.environ, {'DEER_FLOW_HOME': root}), \
             patch('deerflow.config.paths._paths', Paths(root)), \
             patch('deerflow.models.create_chat_model', side_effect=AssertionError('Provider construction forbidden')):
            runtime_config = {'configurable': {'thread_id': 'isolated-full-chain', 'is_plan_mode':False, 'subagent_enabled':False}, 'recursion_limit': 100}
            middlewares = build_middlewares(runtime_config, 'deepseek-flash', app_config=config, memory_enabled=False, user_id='isolated-owner')
            names = [type(m).__name__ for m in middlewares]
            self.assertIn('AfterSalesMiddleware', names)
            self.assertIn('TokenBudgetMiddleware', names)
            print('PINNED_CHAIN=' + ','.join(names))
            graph = create_agent(model, [order], middleware=normalize_middleware_state_schemas(middlewares, 'full'),
                                 state_schema=get_thread_state_schema('full'), context_schema=dict)
            context = {'thread_id':'isolated-full-chain', 'run_id':'isolated-chain-run', 'user_id':'isolated-owner'}
            visited = []
            try:
                async for mode, event in graph.astream({'messages':[HumanMessage(content='本地固定响应验证',id='fixture-human')]},
                    config=runtime_config,context=context,stream_mode=['updates','values']):
                    if mode == 'updates':
                        visited.extend(event)
                    else:
                        result = event
            finally:
                print(f'GRAPH_TRACE model_index={model.i} tool_count={len(calls)} nodes=' + ','.join(visited))
        return result, context, calls, model

    async def test_full_pinned_chain_budget_stops_without_next_tool(self):
        result, context, calls, model = await self.run_fixture()
        self.assertEqual(3, len(calls))
        self.assertEqual('token_capped', context['stop_reason'])
        self.assertEqual([], result['messages'][-1].tool_calls)
        self.assertIn('TOKEN BUDGET EXCEEDED', result['messages'][-1].content)
        self.assertEqual(0, model.i)

    async def test_full_pinned_chain_error_has_no_second_provider_call(self):
        result, context, calls, model = await self.run_fixture(error=True)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, model.i)
        self.assertEqual('ORDER_NOT_FOUND', result['messages'][-1].additional_kwargs['after_sales_non_model_stop'])

    async def test_full_chain_pending_approval_ends_without_provider_summary(self):
        result, context, calls, model = await self.run_fixture(boundary=True)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, model.i)
        final = result['messages'][-1]
        self.assertEqual('awaiting_approval', final.additional_kwargs['after_sales_non_model_terminal'])
        self.assertIn('等待人工审批', final.content)
        self.assertIn('DAMAGE-01', final.content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
