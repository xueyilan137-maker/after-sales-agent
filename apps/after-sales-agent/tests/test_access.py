"""Isolated route authorization regression; simulated users, no real login proof."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sitecustomize
from fastapi import FastAPI
from fastapi.testclient import TestClient
from deerflow_extension_api.auth import ExtensionPrincipal
from after_sales.routes import build_router
from after_sales import store as s


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="after-sales-access-")
        self.env = patch.dict(os.environ, {"AFTER_SALES_DATA_DIR": self.temp.name,
                                         "AFTER_SALES_ENABLE_VERIFICATION": "true"})
        self.env.start()
        s.init_store()
        self.app = FastAPI()
        @self.app.middleware("http")
        async def identity(request, handler):
            request.state.auth_source = request.headers.get("test-auth-source", "session")
            return await handler(request)
        self.app.state.deerflow_extension_principal_resolver = lambda r: (
            ExtensionPrincipal("isolated-owner", is_admin=r.headers.get("test-role") == "admin",
                               is_internal=r.headers.get("test-role") == "internal")
            if r.headers.get("test-role") else None)
        self.app.include_router(build_router(SimpleNamespace(ready=True)))
        self.client = TestClient(self.app)
        order = s.create_demo_run("isolated-owner", "damage-in-window")["order"]
        ticket = s.save_damage_report("isolated-owner", order["order_id"], "裂纹", "隔离测试", "reship")
        self.proposal = s.propose_resolution("isolated-owner", ticket["ticket_id"])["proposals"][0]

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp.cleanup()

    def test_anonymous_and_internal_denied(self):
        for headers in ({}, {"test-role": "internal"}):
            self.assertEqual(401, self.client.get("/api/after-sales/verification", headers=headers).status_code)

    def test_nonadmin_and_api_token_cannot_review(self):
        body = {"expected_digest": self.proposal["digest"], "decision": "approve", "evidence_confirmed": True}
        for headers in ({"test-role": "customer"}, {"test-role": "admin", "test-auth-source": "api_token"}):
            response = self.client.post("/api/after-sales/proposals/" + self.proposal["proposal_id"] + "/review", json=body, headers=headers)
            self.assertEqual(403, response.status_code)
        self.assertEqual("pending", s.get_proposal("isolated-owner", self.proposal["proposal_id"])["status"])

    def test_admin_session_can_review_simulation_only(self):
        response = self.client.post("/api/after-sales/proposals/" + self.proposal["proposal_id"] + "/review",
            json={"expected_digest": self.proposal["digest"], "decision": "approve", "evidence_confirmed": True}, headers={"test-role": "admin"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("approved", response.json()["status"])

    def test_verification_off_and_approval_tool_absent(self):
        with patch.dict(os.environ, {"AFTER_SALES_ENABLE_VERIFICATION": "false"}):
            self.assertEqual(404, self.client.get("/api/after-sales/verification", headers={"test-role": "admin"}).status_code)
        self.assertEqual(422, self.client.post("/api/after-sales/verification/invoke",
            json={"tool": "approve_action", "arguments": {}}, headers={"test-role": "admin"}).status_code)

    def test_model_owner_cannot_enter_business_api(self):
        response = self.client.post("/api/after-sales/tickets", json={"order_id": "ORD-2026-0017", "owner": "forged"}, headers={"test-role": "admin"})
        self.assertEqual(422, response.status_code)

    def test_probe_rejects_owner_and_runtime_before_transport(self):
        transport = AsyncMock()
        tool = SimpleNamespace(name="after-sales-demo_get_demo_order", coroutine=transport,
            tool_call_schema={"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]})
        with patch("deerflow.mcp.tools.get_mcp_tools", new=AsyncMock(return_value=[tool] * 12)):
            for injected in ("owner", "user_id", "runtime", "headers"):
                response = self.client.post("/api/after-sales/verification/invoke",
                    json={"tool": "get_demo_order", "arguments": {"order_id": "ORD-2026-0017", injected: "forged"}},
                    headers={"test-role": "admin"})
                self.assertEqual(422, response.status_code)
        transport.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
