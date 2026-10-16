"""Synthetic business MCP; identity is supplied by trusted host metadata."""

from functools import wraps
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from after_sales.identity import verify_call_metadata
from after_sales.memory_rpc import read_memory_via_gateway as read_memory
from after_sales.policy import search_knowledge, search_policy, load_policy
from after_sales.store import (
    BusinessError, execute_resolution, get_order, get_ticket, propose_resolution,
    get_shipping_events as read_shipping, save_damage_report as save_report, save_logistics_report as save_shipping,
)

mcp = FastMCP("after-sales-demo")


def compact_ticket(ticket: dict, include_policy: bool = False) -> dict:
    # Full evidence/approval/audit records stay in the authenticated workbench;
    # tool turns carry a bounded projection to avoid repeatedly billing history.
    result = {key: ticket[key] for key in (
        "ticket_id", "order_id", "status", "revision", "case_kind", "requested_resolution", "data_kind", "reported_at", "business_reported_at"
    )}
    result["missing_fields"] = [key for key in ("damage_description", "evidence_note", "requested_resolution") if not ticket[key]]
    result["evidence_kind"] = "customer_statement_unverified"
    result["known_information"] = {key: ticket[key][:500] for key in ("damage_description", "evidence_note")}
    result["truncated_fields"] = [key for key in ("damage_description", "evidence_note") if len(ticket[key]) > 500]
    result["attachments"] = [{key: item[key] for key in ("evidence_id", "review_status")} for item in ticket["attachments"]]
    result["clock"] = ticket["order"].get("clock", {"mode": "wall_clock"})
    if ticket["proposals"]:
        proposal = ticket["proposals"][0]
        payload = proposal["payload"]
        result["proposal"] = {
            "proposal_id": proposal["proposal_id"], "status": proposal["status"],
            "expires_at": proposal["expires_at"], "resolution": payload["resolution"],
            "refund_amount_minor": payload["refund_amount_minor"], "currency": payload["currency"],
            "items": payload["items"],
            "citations": [{key: item[key] for key in ("policy_id", "version", "clause_id", "source")} for item in payload["citations"]],
        }
        if include_policy:
            policy = load_policy(ticket['case_kind'], policy_id=payload['policy']['policy_id'], version=payload['policy']['version'])
            if policy['content_sha256'] != payload['policy']['content_sha256']:
                raise ValueError('方案政策内容已变化，请在工作台核对并重新生成方案。')
            result['proposal']['policy_basis'] = [{'clause_id':chunk['clause_id'], 'title':chunk['title'], 'text':chunk['text']}
                for chunk in policy['chunks'] if any(c['clause_id']==chunk['clause_id'] for c in payload['citations'])]
    result["operations"] = ticket["operations"]
    result["followups"] = [{"outcome": item["outcome"], "note": item["note"][:300]} for item in ticket["followups"]]
    if "reasons" in ticket:
        result["reasons"] = ticket["reasons"]
    result["workbench_url"] = "/api/after-sales/workbench"
    return result


def business_call(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BusinessError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.message}, "data_kind": "synthetic_demo_data"}
        except ValueError as exc:
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": str(exc)}, "data_kind": "synthetic_demo_data"}
    return wrapped


@mcp.tool()
@business_call
def get_demo_order(order_id: str, ctx: Context) -> dict:
    """Read the current customer's synthetic demo order. No business mutations."""
    return get_order(verify_call_metadata(ctx), order_id)


@mcp.tool()
@business_call
def search_damage_policy(query: str, ctx: Context, top_k: int = 3, ticket_id: str | None = None) -> dict:
    """Retrieve versioned demo damage-policy clauses with source citations."""
    owner = verify_call_metadata(ctx)
    if ticket_id:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ticket = get_ticket(owner, ticket_id)
        as_of = datetime.fromisoformat(ticket["business_reported_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    else:
        as_of = None
    return search_policy(query, top_k, as_of)


@mcp.tool()
@business_call
def save_damage_report(order_id: str, ctx: Context, damage_description: str | None = None, evidence_note: str | None = None,
                       requested_resolution: Literal["reship", "refund", ""] | None = None, expected_revision: int | None = None) -> dict:
    """Save partial damage info. reship=补发, refund=退款; omit unknown fields, empty string clears. Existing edits need latest revision."""
    return compact_ticket(save_report(verify_call_metadata(ctx), order_id, damage_description, evidence_note, requested_resolution, expected_revision))


@mcp.tool()
@business_call
def get_damage_ticket(ticket_id: str, ctx: Context) -> dict:
    """Read the caller's ticket, approval status and recorded demo result."""
    return compact_ticket(get_ticket(verify_call_metadata(ctx), ticket_id))


@mcp.tool()
@business_call
def propose_damage_resolution(ticket_id: str, ctx: Context) -> dict:
    """Apply deterministic rules and propose a remedy requiring human approval."""
    return compact_ticket(propose_resolution(verify_call_metadata(ctx), ticket_id), include_policy=True)


@mcp.tool()
@business_call
def execute_approved_resolution(proposal_id: str, ctx: Context) -> dict:
    """Record a synthetic remedy only after valid human approval; duplicate-safe."""
    owner = verify_call_metadata(ctx)
    result = execute_resolution(owner, proposal_id)
    ticket = get_ticket(owner, result['ticket_id'])
    operation_ids = [item['operation_id'] for item in ticket['operations']]
    if result['operation_id'] not in operation_ids:
        raise ValueError('演示操作回读不一致，请在工作台核对，不要自动重试。')
    return {**result, 'readback': {'ticket_id':ticket['ticket_id'], 'status':ticket['status'],
        'revision':ticket['revision'], 'operation_ids':operation_ids}}


@mcp.tool()
@business_call
def get_after_sales_ticket(ticket_id: str, ctx: Context) -> dict:
    """Read damage or logistics case, known info, evidence review and approval."""
    return compact_ticket(get_ticket(verify_call_metadata(ctx), ticket_id))


@mcp.tool()
@business_call
def propose_after_sales_resolution(ticket_id: str, ctx: Context) -> dict:
    """Apply damage/logistics rules and create a human-only approval proposal."""
    return compact_ticket(propose_resolution(verify_call_metadata(ctx), ticket_id), include_policy=True)


@mcp.tool()
@business_call
def get_shipping_events(order_id: str, ctx: Context) -> dict:
    """Read synthetic shipping events; never contact a real carrier."""
    return read_shipping(verify_call_metadata(ctx), order_id)


@mcp.tool()
@business_call
def save_logistics_report(order_id: str, ctx: Context, issue_description: str | None = None,
                          evidence_note: str | None = None, expected_revision: int | None = None) -> dict:
    """Save a partial shipping complaint; a remedy is only a demo carrier inquiry."""
    return compact_ticket(save_shipping(verify_call_metadata(ctx), order_id, issue_description, evidence_note, expected_revision))


@mcp.tool()
@business_call
def search_after_sales_knowledge(query: str, ctx: Context, ticket_id: str | None = None,
                                  case_kind: str = "damage", top_k: int = 3) -> dict:
    """Retrieve applicable policy and labelled design examples; use ticket date when known."""
    owner = verify_call_metadata(ctx)
    as_of = None
    if ticket_id:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ticket = get_ticket(owner, ticket_id)
        case_kind = ticket["case_kind"]
        as_of = datetime.fromisoformat(ticket["business_reported_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    return search_knowledge(query, case_kind, as_of, top_k)


@mcp.tool()
@business_call
def get_customer_memory(ctx: Context) -> dict:
    """Read owner-scoped, manually confirmed preferences. Never supplies approval or facts."""
    result = read_memory(verify_call_metadata(ctx))
    # Source notes and edit history are available only in the workbench view.
    result["preferences"] = [{key: item[key] for key in ("key", "value", "confirmed_at", "source_kind")} for item in result["preferences"]]
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
