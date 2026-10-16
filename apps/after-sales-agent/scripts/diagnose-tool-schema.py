"""Offline final model binding probe; real catalog, no provider or tool execution."""
import asyncio
import json
import os
import tempfile
from unittest.mock import patch

import sitecustomize
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from deerflow.config import get_app_config
from deerflow.config.paths import Paths
from deerflow.mcp.cache import initialize_mcp_tools
from deerflow.agents.lead_agent.agent import assemble_lead_agent

captures = []
prompts = []


class BindingProbe(FakeMessagesListChatModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        prompts.append([m.content for m in messages if m.type == 'system'])
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def bind_tools(self, tools, **kwargs):
        captures.append([convert_to_openai_tool(tool) for tool in tools])
        return self


async def main():
    await initialize_mcp_tools()
    config = get_app_config()
    results = []
    for role in ('user', 'admin'):
        with tempfile.TemporaryDirectory(prefix='schema-probe-') as root:
            runtime = {'thread_id': 'schema-probe-' + role, 'run_id': 'schema-probe-' + role,
                       'user_id': 'schema-probe-owner', 'role': role, 'model_name': 'deepseek-flash',
                       'thinking_enabled': False, 'is_plan_mode': False, 'subagent_enabled': False}
            model = BindingProbe(responses=[AIMessage(content='LOCAL_SCHEMA_PROBE',
                usage_metadata={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2})])
            before = len(captures)
            with patch.dict(os.environ, {'DEER_FLOW_HOME': root}), \
                 patch('deerflow.config.paths._paths', Paths(root)), \
                 patch('deerflow.agents.lead_agent.agent.create_chat_model', return_value=model), \
                 patch('deerflow.models.create_chat_model', side_effect=AssertionError('Provider forbidden')):
                assembly = assemble_lead_agent({'configurable': runtime}, app_config=config)
                output = await assembly.graph.ainvoke({'messages': [HumanMessage(content='查询 holdout_qzx_827461，仅只读检索。')]},
                    config={'configurable': runtime, 'recursion_limit': 60}, context=runtime)
            bindings = captures[before:]
            assert len(bindings) == 1
            names = [item['function']['name'] for item in bindings[0]]
            assert 'after-sales-demo_search_after_sales_knowledge' in names
            assert len(names) == 12 and not any(name.startswith('after-sales-demo_approve') for name in names)
            assert all(name in '\n'.join(prompts[-1]) for name in names)
            results.append({'role_context': role, 'bindings': bindings, 'system_messages': prompts[-1],
                            'final': output['messages'][-1].content})
    print('SCHEMA_PROBE_JSON=' + json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
