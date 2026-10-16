"""Short-lived signed caller metadata over the private stdio MCP channel."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

from .store import BusinessError, state_dir


def _signature(user_id: str, issued_at: str) -> str:
    key = (state_dir() / ".identity-key").read_bytes()
    return hmac.new(key, f"{user_id}\n{issued_at}".encode(), hashlib.sha256).hexdigest()


def verify_call_metadata(ctx) -> str:
    metadata = ctx.request_context.meta
    if hasattr(metadata, "model_dump"):
        metadata = metadata.model_dump()
    headers = metadata.get("headers", {}) if isinstance(metadata, Mapping) else {}
    if not isinstance(headers, Mapping):
        raise BusinessError("IDENTITY_REQUIRED", "MCP 调用缺少可信的登录用户身份。", 401)
    user_id = headers.get("x-after-sales-user", "")
    issued_at = headers.get("x-after-sales-issued", "")
    signature = headers.get("x-after-sales-signature", "")
    try:
        age = time.time() - int(issued_at)
        valid = (isinstance(user_id, str) and 0 < len(user_id) <= 128 and user_id != "default"
                 and -5 <= age <= 60 and hmac.compare_digest(signature, _signature(user_id, issued_at)))
    except (ValueError, TypeError, OSError):
        valid = False
    if not valid:
        raise BusinessError("IDENTITY_REQUIRED", "MCP 调用缺少可信的登录用户身份。", 401)
    return user_id


def build_identity_interceptor():
    async def interceptor(request, handler):
        if request.server_name != "after-sales-demo":
            return await handler(request)
        runtime = getattr(request, "runtime", None)
        if runtime is None:
            from langgraph.runtime import get_runtime
            runtime = get_runtime()
        context = getattr(runtime, "context", {})
        user_id = context.get("user_id") if isinstance(context, Mapping) else None
        if not isinstance(user_id, str) or not user_id or user_id == "default":
            from langchain_core.tools import ToolException
            raise ToolException("After-sales tools require the authenticated run owner.")
        issued_at = str(int(time.time()))
        headers = dict(request.headers or {})
        headers.update({"x-after-sales-user": user_id, "x-after-sales-issued": issued_at,
                        "x-after-sales-signature": _signature(user_id, issued_at)})
        return await handler(request.override(headers=headers))
    return interceptor
