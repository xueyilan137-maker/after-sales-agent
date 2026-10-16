"""Gateway plugin plus operator-configured transforming Agent middleware."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from pathlib import Path

from deerflow_extension_api import extension
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .store import init_store
from . import __version__
from .customer_memory import close_memory, manager

TOOL_NAMES = {
    "get_demo_order", "search_damage_policy", "save_damage_report", "get_after_sales_ticket",
    "propose_after_sales_resolution", "execute_approved_resolution", "get_shipping_events",
    "save_logistics_report", "search_after_sales_knowledge", "get_customer_memory",
}
ALLOWED = {"read_file", "ask_clarification", *("after-sales-demo_" + name for name in TOOL_NAMES)}
SKILL_PATHS = {f"/mnt/skills/public/{name}/SKILL.md" for name in ("damage-intake", "logistics-investigation")}
logger = logging.getLogger(__name__)


class AfterSalesMiddleware(AgentMiddleware):
    def __init__(self, token_budget=None):
        self.prompt = (Path(__file__).parent / "prompts/service.md").read_text(encoding="utf-8")
        from deerflow.config import get_app_config
        from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
        # Reuse the pinned budget's accounting/stripping, with the same limits.
        # This configured hook precedes the host budget in reverse after-model
        # order and explicitly routes a capped response to end, without relying
        # on the remaining host hook nodes to reach a natural exit.
        config = token_budget if token_budget is not None else get_app_config().token_budget
        # Host alone injects the soft warning. This adapter only needs the same
        # hard limits; do not enqueue a duplicate warning in a second instance.
        self.budget = TokenBudgetMiddleware.from_config(config.model_copy(update={"warn_threshold": config.hard_stop_threshold}))
        from deerflow.agents.middlewares._bounded_dict import BoundedDict
        self._budget_started = BoundedDict(1000)
        self._budget_lock = threading.Lock()

    def begin_budget(self, state, runtime):
        context = runtime.context or {}
        key = context.get("run_id") or id(getattr(runtime, "control", runtime))
        with self._budget_lock:
            if key not in self._budget_started:
                self.budget.before_agent(state, runtime)
                self._budget_started[key] = True

    def cap_response(self, request, response):
        state = {**request.state, "messages": [*request.state.get("messages", []), *response.result]}
        update = self.budget.after_model(state, request.runtime)
        if update is not None:
            response.result = [message.model_copy(update={"additional_kwargs": {
                **message.additional_kwargs, "after_sales_budget_capped": True}}) for message in update["messages"]]
        return response

    @hook_config(can_jump_to=["end"])
    def after_model(self, state, runtime):
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].additional_kwargs.get("after_sales_budget_capped"):
            logger.info("after_sales_budget_stop jump_to=end")
            return {"jump_to": "end"}
        return None

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)

    def release_policy_parameters(self):
        return {"business_profile": "after-sales-v" + __version__, "allowed_tools": sorted(ALLOWED),
                "prompt_strategy": "compact_system_historical_result_pointers", "approval_tool": False}

    def transform(self, request):
        # Persisted history and host-injected date reminders stay intact;
        # old tool bodies are projected only in this provider-request copy.
        tools = [tool for tool in request.tools if getattr(tool, "name", None) in ALLOWED]
        # Derive the spelling guide from this request's admitted schemas. Never
        # advertise absent tools or silently repair a model's invalid tool call.
        catalog = '\n'.join(sorted({tool.name for tool in tools}))
        prompt = self.prompt + '\n本次可调用工具完整名称：\n' + catalog
        return request.override(system_message=SystemMessage(content=prompt), tools=tools,
                                messages=self.compact_model_messages(request.messages))

    @staticmethod
    def compact_model_messages(messages):
        # Request-only projection; all messages/checkpoints/audit stay intact.
        # Current-turn results remain complete. Earlier successful, paired
        # business snapshots can defer nested bodies to explicit reread pointers.
        latest_user = max((i for i,m in enumerate(messages) if isinstance(m, HumanMessage)
            and m.name != 'budget_warning' and not m.additional_kwargs.get('hide_from_ui')), default=-1)
        from .context_projection import historical_pointers
        pointers = historical_pointers(messages, latest_user)
        result = []
        for index, message in enumerate(messages):
            if index in pointers:
                result.append(pointers[index])
                continue
            if not isinstance(message, ToolMessage) or message.name not in ALLOWED or message.name == "read_file":
                result.append(message)
                continue
            blocks = message.content if isinstance(message.content, list) else [message.content]
            compact = []
            for block in blocks:
                raw = block.get("text") if isinstance(block, dict) and block.get("type") == "text" else block
                if isinstance(raw, str):
                    try:
                        payload = json.loads(raw)
                        if index < latest_user and message.name == 'after-sales-demo_propose_after_sales_resolution' and isinstance(payload, dict):
                            proposal = payload.get('proposal')
                            if isinstance(proposal, dict) and proposal.get('citations') and 'policy_basis' in proposal:
                                proposal.pop('policy_basis')
                                proposal['policy_basis_deferred_to_sources'] = True
                        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                    except (ValueError, TypeError):
                        compact.append(block)
                        continue
                    compact.append({**block, "text": raw} if isinstance(block, dict) else raw)
                else:
                    compact.append(block)
            content = compact if isinstance(message.content, list) else compact[0]
            result.append(message.model_copy(update={"content": content}))
        return result

    def wrap_model_call(self, request, handler):
        stopped = self.tool_failure_response(request) or self.business_boundary_response(request)
        if stopped is not None:
            return stopped
        self.begin_budget(request.state, request.runtime)
        start = time.monotonic()
        response = handler(self.transform(request))
        self.observe(response, start)
        return self.cap_response(request, response)

    async def awrap_model_call(self, request, handler):
        stopped = self.tool_failure_response(request) or self.business_boundary_response(request)
        if stopped is not None:
            return stopped
        self.begin_budget(request.state, request.runtime)
        start = time.monotonic()
        response = await handler(self.transform(request))
        self.observe(response, start)
        return self.cap_response(request, response)

    def tool_failure_response(self, request):
        # A failed batch ends locally, before another provider request. Business
        # errors are JSON {ok:false} even when the MCP ToolMessage status is
        # success; transport/schema failures use status=error. Do not scan older
        # turns or interpret arbitrary retrieved prose as an error instruction.
        state = getattr(request, "state", None)
        messages = state.get("messages", request.messages) if isinstance(state, dict) else request.messages
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                break
            # Framework/deny results may have no name, or the rejected name.
            # Any actual failed tool batch must stop before another provider
            # call; only successful unknown prose is excluded from inspection.
            if message.name not in ALLOWED and message.status != "error":
                continue
            code = "TOOL_ERROR" if message.status == "error" else None
            blocks = message.content if isinstance(message.content, list) else [message.content]
            for block in blocks:
                raw = block.get("text") if isinstance(block, dict) else block
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("ok") is False:
                    error = payload.get("error")
                    if isinstance(error, dict):
                        candidate = error.get("code")
                        if isinstance(candidate, str) and candidate.replace("_", "").isalnum() and len(candidate) <= 80:
                            code = candidate
            if code:
                logger.info("after_sales_tool_error_stop code=%s provider_called=false", code)
                return ModelResponse(result=[AIMessage(id="after-sales-stop-" + uuid.uuid4().hex,
                    content=f"工具返回 {code}，本轮已停止。请在售后工作台核对工单状态并处理错误后再继续：/api/after-sales/workbench。演示处理完成与否以工单记录为准。",
                    additional_kwargs={"after_sales_non_model_stop": code})])
        return None

    def business_boundary_response(self, request):
        # Deterministic handoff/receipt, sourced solely from the latest completed
        # signed business tool. Does not approve, execute or change any state.
        state = getattr(request, "state", None)
        messages = state.get("messages", request.messages) if isinstance(state, dict) else request.messages
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                break
            if message.status == "error":
                continue
            name = (message.name or "").removeprefix("after-sales-demo_")
            if name not in {"propose_after_sales_resolution", "execute_approved_resolution"}:
                continue
            blocks = message.content if isinstance(message.content, list) else [message.content]
            for block in blocks:
                raw = block.get("text") if isinstance(block, dict) else block
                try:
                    payload = json.loads(raw) if isinstance(raw, str) else None
                except ValueError:
                    continue
                if not isinstance(payload, dict) or payload.get("data_kind") != "synthetic_demo_data":
                    continue
                if name == "propose_after_sales_resolution" and payload.get("status") == "awaiting_approval":
                    proposal = payload.get("proposal", {})
                    if proposal.get("status") != "pending":
                        continue
                    citations = proposal.get("citations", [])
                    basis = "；".join(f"{c['policy_id']} v{c['version']} {c['clause_id']}" for c in citations)
                    content = f"合成演示：工单 {payload['ticket_id']}，方案 {proposal['proposal_id']}，当前等待人工审批。政策依据：{basis}。请在售后工作台核验资料和方案后审批：/api/after-sales/workbench。尚未执行退款、补发或物流调查。"
                    boundary = "awaiting_approval"
                elif name == "execute_approved_resolution":
                    readback = payload.get("readback", {})
                    if payload.get("operation_id") not in readback.get("operation_ids", []) or readback.get("status") not in {"resolved", "awaiting_followup"}:
                        continue
                    content = f"合成演示操作 {payload['operation_id']} 已记录；回读工单 {readback['ticket_id']} 状态为 {readback['status']}，revision={readback['revision']}。没有真实付款、发货或承运方联络。" \
                        + ("请在工作台记录人工最终跟进。" if readback['status'] == "awaiting_followup" else "本次演示工单已完成。")
                    boundary = readback['status']
                else:
                    continue
                logger.info("after_sales_boundary_stop state=%s provider_called=false", boundary)
                return ModelResponse(result=[AIMessage(id="after-sales-receipt-" + uuid.uuid4().hex,
                    content=content, additional_kwargs={"after_sales_non_model_terminal":boundary})])
        return None

    def observe(self, response, start):
        # Metadata only. No prompt, customer text, API key or currency estimate.
        try:
            usage = [getattr(message, "usage_metadata", None) for message in response.result]
            logger.info("after_sales_model_usage profile=%s elapsed_ms=%d usage=%s", __version__, int((time.monotonic() - start) * 1000), [item for item in usage if item])
        except Exception:
            logger.warning("after_sales_model_usage unavailable")

    def denied(self, request):
        call = request.tool_call
        name = call.get("name", "")
        args = call.get("args", {})
        blocked = name not in ALLOWED
        if name == "read_file":
            blocked = args.get("path") not in SKILL_PATHS
        if blocked:
            return ToolMessage(content="当前售后业务配置不允许此工具或文件路径。", tool_call_id=call["id"], status="error")
        return None

    def wrap_tool_call(self, request, handler):
        denial = self.denied(request)
        return denial if denial is not None else handler(request)

    async def awrap_tool_call(self, request, handler):
        denial = self.denied(request)
        return denial if denial is not None else await handler(request)


class BusinessService:
    ready = False

    async def start(self, deps):
        await asyncio.to_thread(init_store)
        await asyncio.to_thread(manager)
        from .memory_rpc import MemoryReadServer
        self.memory_reader = MemoryReadServer()
        await self.memory_reader.start()
        self.ready = True

    async def stop(self):
        self.ready = False
        if getattr(self, 'memory_reader', None) is not None:
            await self.memory_reader.stop()
        await asyncio.to_thread(close_memory)


@extension(api="0.2.0", name="after-sales")
def install(registry, config):
    from .routes import build_router
    service = BusinessService()
    # Packaged extension middleware is observational in this pinned release.
    # AfterSalesMiddleware is registered through extensions_config.middlewares,
    # whose documented operator-owned API supports request transformation/deny.
    registry.service(service)
    registry.routers((build_router(service),))
