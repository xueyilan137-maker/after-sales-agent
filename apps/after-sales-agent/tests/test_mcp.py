"""Layer 2 transport regression in isolated state; no authenticated UI claim.

Uses the real pinned loader/interceptor/stdio server with simulated runtime owners,
and raw MCP SDK calls to check missing/invalid metadata. No model constructed.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import sitecustomize
from langchain.tools import ToolRuntime
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.tools import get_mcp_tools
from deerflow.mcp.session_pool import get_session_pool
from after_sales import store as s
from after_sales.identity import _signature
from after_sales.plugin import TOOL_NAMES, AfterSalesMiddleware, SKILL_PATHS


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="after-sales-mcp-")
        source = json.loads(ExtensionsConfig.resolve_config_path().read_text())
        env = source["mcpServers"]["after-sales-demo"]["env"]
        env["AFTER_SALES_DATA_DIR"] = self.temp.name
        env["PYTHONPATH"] = "/tmp/after-sales-verification:/app/backend"
        path = Path(self.temp.name) / "extensions.json"
        path.write_text(json.dumps(source))
        self.env = patch.dict(os.environ, {"AFTER_SALES_DATA_DIR": self.temp.name,
            "DEER_FLOW_HOME": self.temp.name + "/harness", "DEER_FLOW_EXTENSIONS_CONFIG_PATH": str(path)})
        self.env.start()
        s.init_store()
        from after_sales import customer_memory as memory
        from after_sales.memory_rpc import MemoryReadServer
        memory.close_memory()
        await asyncio.to_thread(memory.manager)
        self.memory_reader = MemoryReadServer()
        await self.memory_reader.start()
        self.tools = {t.name.removeprefix("after-sales-demo_"): t for t in await get_mcp_tools()}

    async def asyncTearDown(self):
        await get_session_pool().close_all()
        await self.memory_reader.stop()
        from after_sales.customer_memory import close_memory
        close_memory()
        self.env.stop()
        self.temp.cleanup()

    async def call(self, name, args, owner="isolated-owner-a", thread_id="isolated-mcp"):
        runtime = ToolRuntime(state={}, context={"user_id": owner}, config={"configurable": {"thread_id": thread_id}},
                              stream_writer=lambda _: None, tool_call_id="isolated", store=None)
        content, artifact = await self.tools[name].coroutine(runtime=runtime, **args)
        return artifact["structured_content"] if artifact else json.loads(content[0]["text"])

    async def test_three_fresh_threads_read_empty_memory(self):
        for index in range(3):
            started=time.monotonic()
            result=await self.call('get_customer_memory',{},thread_id='isolated-cold-'+str(index))
            self.assertEqual([],result['preferences'])
            self.assertFalse(result['auto_extraction'])
            print('FRESH_MEMORY_SESSION_SECONDS='+str(round(time.monotonic()-started,3)))

    async def test_directory_and_restricted_skills(self):
        self.assertEqual(12, len(self.tools))
        self.assertEqual(10, len(TOOL_NAMES))
        self.assertFalse(any("approve" in name and name != "execute_approved_resolution" for name in self.tools))
        for tool in self.tools.values():
            self.assertFalse({"owner", "user_id", "ctx", "runtime"} & set(tool.tool_call_schema["properties"]))
        middleware = AfterSalesMiddleware()
        from types import SimpleNamespace
        for path in SKILL_PATHS:
            name = path.split("/")[-2]
            self.assertTrue(Path("/app/after-sales-skills/public/" + name + "/SKILL.md").is_file())
            self.assertIsNone(middleware.denied(SimpleNamespace(tool_call={"id": "1", "name": "read_file", "args": {"path": path}})))
        denied = middleware.denied(SimpleNamespace(tool_call={"id": "1", "name": "read_file", "args": {"path": "/app/after-sales-data/.identity-key"}}))
        self.assertEqual("error", denied.status)

    async def test_cold_signed_memory_read_correct_forget_and_isolation(self):
        from after_sales import customer_memory as memory
        memory.close_memory()
        try:
            first = memory.save_preference('isolated-owner-a','resolution_preference','reship','私有来源不应进入MCP')['preferences'][0]
            started = time.monotonic()
            result = await self.call('get_customer_memory', {})
            self.assertEqual('reship',result['preferences'][0]['value'])
            self.assertNotIn('source_note',result['preferences'][0])
            self.assertEqual([], (await self.call('get_customer_memory', {}, 'isolated-owner-b'))['preferences'])
            second = memory.save_preference('isolated-owner-a','resolution_preference','refund','纠正',first['digest'])['preferences'][0]
            self.assertEqual('refund',(await self.call('get_customer_memory', {}))['preferences'][0]['value'])
            memory.forget_preference('isolated-owner-a',second['fact_id'],second['digest'])
            self.assertEqual([], (await self.call('get_customer_memory', {}))['preferences'])
            print('COLD_SIGNED_MEMORY_SECONDS=' + str(round(time.monotonic()-started,3)))
        finally:
            memory.close_memory()

    async def test_signed_loader_calls_and_isolation(self):
        owner = "isolated-owner-a"
        order = s.create_demo_run(owner, "damage-in-window")["order"]
        found = await self.call("get_demo_order", {"order_id": order["order_id"]})
        self.assertTrue(found["found"])
        denied = await self.call("get_demo_order", {"order_id": order["order_id"]}, "isolated-owner-b")
        self.assertEqual("ORDER_NOT_FOUND", denied["error"]["code"])
        ticket = await self.call("save_damage_report", {"order_id": order["order_id"], "damage_description": "合成裂纹", "evidence_note": "工程测试", "requested_resolution": "reship"})
        proposal = (await self.call("propose_after_sales_resolution", {"ticket_id": ticket["ticket_id"]}))["proposal"]
        self.assertTrue(proposal['policy_basis'])
        self.assertEqual({c['clause_id'] for c in proposal['citations']}, {c['clause_id'] for c in proposal['policy_basis']})
        self.assertTrue(all(c['text'] for c in proposal['policy_basis']))
        refused = await self.call("execute_approved_resolution", {"proposal_id": proposal["proposal_id"]})
        self.assertEqual("HUMAN_APPROVAL_REQUIRED", refused["error"]["code"])
        readback = await self.call("get_after_sales_ticket", {"ticket_id": ticket["ticket_id"]})
        self.assertEqual("awaiting_approval", readback["status"])
        self.assertEqual([], readback["operations"])
        self.assertFalse((await self.call("get_customer_memory", {}))["auto_extraction"])

    async def test_resolution_enum_rejects_before_business_write(self):
        from jsonschema import validate, ValidationError
        schema = self.tools['save_damage_report'].tool_call_schema
        for value in ('reship', 'refund', '', None):
            validate({'order_id': 'fixture', 'requested_resolution': value}, schema)
        with self.assertRaises(ValidationError):
            validate({'order_id': 'fixture', 'requested_resolution': '补发'}, schema)
        order = s.create_demo_run('isolated-owner-a', 'damage-in-window')['order']
        with self.assertRaises(Exception) as caught:
            await self.call('save_damage_report', {'order_id': order['order_id'], 'requested_resolution': '补发'})
        self.assertIn('reship', str(caught.exception))
        with s.connect() as conn:
            self.assertEqual(0, conn.execute('SELECT count(*) FROM tickets').fetchone()[0])

    async def test_signed_execution_returns_committed_readback(self):
        owner = 'isolated-owner-a'
        order = s.create_demo_run(owner, 'damage-in-window')['order']
        ticket = await self.call('save_damage_report', {'order_id':order['order_id'], 'damage_description':'合成裂纹', 'evidence_note':'隔离回归', 'requested_resolution':'reship'})
        await self.call('propose_after_sales_resolution', {'ticket_id':ticket['ticket_id']})
        proposal = s.get_ticket(owner, ticket['ticket_id'])['proposals'][0]
        s.review_proposal(owner, proposal['proposal_id'], proposal['digest'], 'approve', '模拟审批，仅隔离回归', True)
        result = await self.call('execute_approved_resolution', {'proposal_id':proposal['proposal_id']})
        self.assertEqual('resolved', result['readback']['status'])
        self.assertIn(result['operation_id'], result['readback']['operation_ids'])
        repeat = await self.call('execute_approved_resolution', {'proposal_id':proposal['proposal_id']})
        self.assertTrue(repeat['idempotent_reuse'])
        self.assertEqual(result['operation_id'], repeat['operation_id'])
        self.assertEqual(1, len(repeat['readback']['operation_ids']))

    async def test_raw_stdio_rejects_missing_expired_and_bad_signatures(self):
        parameters = StdioServerParameters(command="/app/backend/.venv/bin/python", args=["/app/business-mcp/after_sales_mcp/__main__.py"],
            env={"PYTHONPATH": "/tmp/after-sales-verification:/app/backend", "AFTER_SALES_DATA_DIR": self.temp.name})
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                issued = str(int(time.time()))
                good = {"x-after-sales-user": "isolated-owner-a", "x-after-sales-issued": issued,
                        "x-after-sales-signature": _signature("isolated-owner-a", issued)}
                expired = str(int(issued) - 61)
                bad = [None, {"headers": {}}, {"headers": {**good, "x-after-sales-signature": "bad"}},
                    {"headers": {**good, "x-after-sales-issued": expired, "x-after-sales-signature": _signature("isolated-owner-a", expired)}},
                    {"headers": {**good, "x-after-sales-user": "forged-owner"}}]
                for meta in bad:
                    result = await session.call_tool("get_demo_order", {"order_id": "ORD-2026-0017"}, meta=meta)
                    payload = result.structuredContent or json.loads(result.content[0].text)
                    self.assertEqual("IDENTITY_REQUIRED", payload["error"]["code"])
                result = await session.call_tool("get_demo_order", {"order_id": "ORD-2026-0017"}, meta={"headers": good})
                payload = result.structuredContent or json.loads(result.content[0].text)
                self.assertTrue(payload["found"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
