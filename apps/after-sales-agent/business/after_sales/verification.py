"""Opt-in, administrator-only MCP integration probe. Never constructs an Agent.

The pinned loader, runtime owner injection, interceptors and stdio tools are real.
User-selected calls are engineering evidence, not model-selected Agent evidence.
"""
import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from jsonschema import validate, ValidationError


def tool_schema(tool):
    schema = tool.tool_call_schema
    return schema if isinstance(schema, dict) else schema.model_json_schema()


class ProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict = Field(default_factory=dict)


def install_probe(router, interactive_admin):
    def enabled(identity=Depends(interactive_admin)):
        if os.environ.get("AFTER_SALES_ENABLE_VERIFICATION") != "true":
            raise HTTPException(404, "非模型验证入口未启用。")
        return identity

    async def loaded_tools():
        from deerflow.config.extensions_config import ExtensionsConfig
        from deerflow.mcp.tools import get_mcp_tools
        configuration = ExtensionsConfig.from_file()
        servers = {name: item for name, item in configuration.mcp_servers.items() if item.enabled}
        server = servers.get("after-sales-demo")
        if (set(servers) != {"after-sales-demo"} or server.type != "stdio"
                or server.command != "/app/backend/.venv/bin/python"
                or server.args != ["/app/business-mcp/after_sales_mcp/__main__.py"]):
            raise HTTPException(409, "验证只允许固定本地售后 stdio 服务。")
        tools = await asyncio.wait_for(get_mcp_tools(), timeout=40)
        if len(tools) != 12:
            raise HTTPException(503, "售后 MCP 工具目录不完整。")
        return tools

    @router.get("/verification", response_class=HTMLResponse)
    def page(identity=Depends(enabled)):
        return HTMLResponse((Path(__file__).parent / "web/verification.html").read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @router.get("/verification/tools")
    async def discover(identity=Depends(enabled)):
        from .plugin import TOOL_NAMES
        tools = await loaded_tools()
        return {"mode": "non_model_mcp_verification", "model_called": False,
                "tools": [{"name": t.name, "schema": tool_schema(t)} for t in tools],
                "model_allowlist": sorted(TOOL_NAMES), "approval_tool": False}

    @router.post("/verification/invoke")
    async def invoke(body: ProbeInput, request: Request, identity=Depends(enabled)):
        from app.gateway.services import inject_authenticated_user_context
        from langchain.tools import ToolRuntime
        from deerflow.mcp.session_pool import get_session_pool
        from .plugin import TOOL_NAMES
        if body.tool not in TOOL_NAMES:
            raise HTTPException(422, "工具不在售后模型白名单中。")
        if len(json.dumps(body.arguments, ensure_ascii=False)) > 10000:
            raise HTTPException(422, "验证参数过长。")
        tools = await loaded_tools()
        tool = next(t for t in tools if t.name == "after-sales-demo_" + body.tool)
        schema = tool_schema(tool)
        allowed_arguments = set(schema.get("properties", {}))
        if set(body.arguments) - allowed_arguments:
            raise HTTPException(422, "参数必须匹配 MCP schema；不接受身份、runtime 或签名参数。")
        # Explicitly exclude injected/runtime fields and validate business input
        # before invoking the real loader's persistent-session coroutine.
        try:
            validate(body.arguments, schema)
        except ValidationError as exc:
            raise HTTPException(422, "参数不符合 MCP schema。") from exc
        thread = "mcp-verification-" + uuid.uuid4().hex
        config = {"configurable": {"thread_id": thread}, "context": {}}
        inject_authenticated_user_context(config, request)
        if config["context"].get("user_id") != identity.user_id:
            raise HTTPException(403, "登录身份与运行上下文不一致。")
        runtime = ToolRuntime(state={}, context=config["context"], config=config,
                              stream_writer=lambda _: None, tool_call_id=thread, store=None)
        pool = get_session_pool()
        try:
            content, artifact = await asyncio.wait_for(tool.coroutine(runtime=runtime, **body.arguments), timeout=40)
            return {"mode": "non_model_mcp_verification", "model_called": False,
                    "probe_id": thread, "tool": tool.name, "content": content, "artifact": artifact}
        finally:
            await pool.close_scope(identity.user_id + ":" + thread)
