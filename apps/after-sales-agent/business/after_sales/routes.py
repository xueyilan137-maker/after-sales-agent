"""Authenticated business APIs and a human-only approval workbench."""

from pathlib import Path

from deerflow_extension_api.auth import resolve_principal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .customer_memory import forget_preference, get_customer_memory, save_preference
from .evidence import MAX_BYTES, add_evidence, read_evidence, review_evidence
from .policy import case_document, load_policy, search_knowledge
from .scenarios import catalog
from .store import (
    BusinessError, create_demo_run, execute_resolution, get_order, get_proposal, get_ticket, list_demo_runs, list_events, list_tickets,
    propose_resolution, record_shipping_followup, review_proposal, save_damage_report, save_logistics_report,
)


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=64)
    damage_description: str | None = Field(default=None, max_length=2000)
    evidence_note: str | None = Field(default=None, max_length=2000)
    requested_resolution: str | None = Field(default=None, max_length=16)
    expected_revision: int | None = Field(default=None, ge=1)
    case_kind: str = Field(default="damage", pattern="^(damage|logistics)$")


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(min_length=64, max_length=64)
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=1000)
    evidence_confirmed: bool = False


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=64)


class EvidenceReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(accepted|rejected)$")
    note: str = Field(min_length=1, max_length=1000)
    expected_revision: int = Field(ge=1)


class FollowupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = Field(pattern="^(delivered|manual_review)$")
    note: str = Field(min_length=1, max_length=1000)
    expected_revision: int = Field(ge=1)


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=32)
    value: str = Field(max_length=32)
    source_note: str = Field(min_length=1, max_length=500)
    expected_digest: str | None = Field(default=None, min_length=64, max_length=64)


class ForgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(min_length=64, max_length=64)


def invoke(fn, *args):
    try:
        return fn(*args)
    except BusinessError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_INPUT", "message": str(exc)}) from exc


def build_router(service):
    def principal(request: Request):
        identity = resolve_principal(request)
        if identity is None or not identity.user_id or identity.is_internal:
            raise HTTPException(401, "需要登录用户。")
        if not service.ready:
            raise HTTPException(503, "售后业务服务尚未就绪。")
        return identity

    def interactive_admin(request: Request, identity=Depends(principal)):
        # Use the pinned host's verified auth source. API tokens, internal agents
        # and auth-disabled mode cannot approve through this endpoint.
        if not identity.is_admin or getattr(request.state, "auth_source", None) != "session":
            raise HTTPException(403, "审批和手动执行需要交互式管理员登录。")
        return identity

    def interactive_session(request: Request, identity=Depends(principal)):
        if getattr(request.state, "auth_source", None) != "session":
            raise HTTPException(403, "此操作需要交互式登录会话。")
        return identity

    router = APIRouter(prefix="/api/after-sales", tags=["after-sales"])

    @router.get("/status")
    def status(request: Request, identity=Depends(principal)):
        return {"version": __version__, "ready": service.ready, "data_kind": "synthetic_demo_data",
                "human_review_available": identity.is_admin and getattr(request.state, "auth_source", None) == "session",
                "schema_version": 2, "vision_analysis": False, "memory_auto_extraction": False,
                "original_report_deadline": "2026-10-15T14:30:00+08:00"}

    @router.get("/workbench", response_class=HTMLResponse)
    def workbench(identity=Depends(principal)):
        return HTMLResponse((Path(__file__).parent / "web/workbench.html").read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                     "Referrer-Policy": "same-origin"})

    @router.get("/assets/workbench.js")
    def workbench_script(identity=Depends(principal)):
        return Response((Path(__file__).parent / "web/workbench.js").read_text(encoding="utf-8"),
                        media_type="text/javascript", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @router.get("/policies/{policy_id}", response_class=HTMLResponse)
    def policy_document(policy_id: str, version: str | None = None, identity=Depends(principal)):
        import html
        try:
            policy = load_policy("logistics" if policy_id.startswith("logistics-") else "damage", policy_id=policy_id, version=version)
        except ValueError:
            raise HTTPException(404, "政策不存在。")
        # Escape all document text; no raw Markdown HTML enters the page.
        clauses = "".join(f'<section id="{item["clause_id"]}"><h2>{html.escape(item["clause_id"] + " " + item["title"])}</h2><p>{html.escape(item["text"])}</p></section>' for item in policy["chunks"])
        body = f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{html.escape(policy["title"])}</title><body style="max-width:800px;margin:50px auto;padding:20px;font:17px/1.8 serif"><a href="/api/after-sales/workbench">返回工单工作台</a><h1>{html.escape(policy["title"])}</h1><p>合成演示政策 · 版本 {html.escape(policy["version"])} · 生效日 {policy["effective_from"]}</p>{clauses}</body></html>'
        return HTMLResponse(body, headers={"Cache-Control": "no-store"})

    @router.get("/tickets")
    def tickets(before: str | None = Query(None, max_length=256), limit: int = Query(30, ge=1, le=50), identity=Depends(principal)):
        return invoke(list_tickets, identity.user_id, before, limit)

    @router.get("/scenarios")
    def scenarios(identity=Depends(principal)):
        return catalog()

    @router.post("/demo-runs")
    def demo_run(body: ScenarioInput, identity=Depends(interactive_session)):
        return invoke(create_demo_run, identity.user_id, body.scenario_id)

    @router.get("/demo-runs")
    def demo_runs(identity=Depends(principal)):
        return invoke(list_demo_runs, identity.user_id)

    @router.get("/orders/{order_id}")
    def order(order_id: str, identity=Depends(principal)):
        return invoke(get_order, identity.user_id, order_id)

    @router.get("/knowledge")
    def knowledge(query: str = Query(min_length=1, max_length=500), case_kind: str = "damage", as_of: str | None = None, ticket_id: str | None = None,
                  top_k: int = Query(3, ge=1, le=5), identity=Depends(principal)):
        if ticket_id:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            ticket = invoke(get_ticket, identity.user_id, ticket_id)
            case_kind = ticket["case_kind"]
            as_of = datetime.fromisoformat(ticket["business_reported_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        return invoke(search_knowledge, query, case_kind, as_of, top_k)

    @router.get("/cases/{case_id}")
    def case(case_id: str, identity=Depends(principal)):
        try:
            return {**case_document(case_id), "data_kind": "synthetic_design_example", "authority": "illustration_only"}
        except StopIteration:
            raise HTTPException(404, "案例不存在。")

    @router.get("/tickets/{ticket_id}")
    def ticket(ticket_id: str, identity=Depends(principal)):
        return invoke(get_ticket, identity.user_id, ticket_id)

    @router.get("/tickets/{ticket_id}/events")
    def events(ticket_id: str, before: int | None = Query(None, ge=1), limit: int = Query(30, ge=1, le=100), identity=Depends(principal)):
        return invoke(list_events, identity.user_id, ticket_id, before, limit)

    @router.post("/tickets")
    def report(body: ReportInput, identity=Depends(principal)):
        if body.case_kind == "logistics":
            if body.requested_resolution not in {None, "", "carrier_inquiry"}:
                raise HTTPException(422, "物流异常只支持调查登记。")
            return invoke(save_logistics_report, identity.user_id, body.order_id, body.damage_description, body.evidence_note, body.expected_revision)
        return invoke(save_damage_report, identity.user_id, body.order_id, body.damage_description,
                      body.evidence_note, body.requested_resolution, body.expected_revision)

    @router.post("/tickets/{ticket_id}/evidence")
    async def upload_evidence(ticket_id: str, request: Request, filename: str = Query(min_length=1, max_length=120),
                              expected_revision: int = Query(ge=1), identity=Depends(interactive_session)):
        # Bound the stream before decoding. Raw bytes avoid multipart buffering.
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, detail={"code": "EVIDENCE_SIZE_LIMIT", "message": "附件不得超过 4 MiB。"})
            payload.extend(chunk)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(invoke, add_evidence, identity.user_id, ticket_id, bytes(payload), filename,
                                       request.headers.get("content-type", "").split(";")[0], expected_revision)

    @router.get("/evidence/{evidence_id}")
    def evidence_file(evidence_id: str, identity=Depends(principal)):
        result = invoke(read_evidence, identity.user_id, evidence_id)
        return Response(result["content"], media_type=result["media_type"], headers={"Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline", "ETag": '"' + result["sha256"] + '"'})

    @router.post("/tickets/{ticket_id}/evidence/{evidence_id}/review")
    def evidence_review(ticket_id: str, evidence_id: str, body: EvidenceReviewInput, identity=Depends(interactive_admin)):
        return invoke(review_evidence, identity.user_id, ticket_id, evidence_id, body.decision, body.note, body.expected_revision)

    @router.post("/tickets/{ticket_id}/proposal")
    def proposal(ticket_id: str, identity=Depends(principal)):
        return invoke(propose_resolution, identity.user_id, ticket_id)

    @router.post("/proposals/{proposal_id}/review")
    def review(proposal_id: str, body: ReviewInput, identity=Depends(interactive_admin)):
        return invoke(review_proposal, identity.user_id, proposal_id, body.expected_digest, body.decision, body.note, body.evidence_confirmed)

    @router.get("/proposals/{proposal_id}")
    def proposal_history(proposal_id: str, identity=Depends(principal)):
        return invoke(get_proposal, identity.user_id, proposal_id)

    @router.post("/proposals/{proposal_id}/execute")
    def execute(proposal_id: str, identity=Depends(interactive_admin)):
        return invoke(execute_resolution, identity.user_id, proposal_id)

    @router.post("/tickets/{ticket_id}/followup")
    def followup(ticket_id: str, body: FollowupInput, identity=Depends(interactive_admin)):
        return invoke(record_shipping_followup, identity.user_id, ticket_id, body.outcome, body.note, body.expected_revision)

    @router.get("/customer-memory")
    def memory(identity=Depends(principal)):
        return invoke(get_customer_memory, identity.user_id)

    @router.post("/customer-memory")
    def remember(body: MemoryInput, identity=Depends(interactive_admin)):
        return invoke(save_preference, identity.user_id, body.key, body.value, body.source_note, body.expected_digest)

    @router.post("/customer-memory/{fact_id}/forget")
    def forget(fact_id: str, body: ForgetInput, identity=Depends(interactive_admin)):
        return invoke(forget_preference, identity.user_id, fact_id, body.expected_digest)

    from .verification import install_probe
    install_probe(router, interactive_admin)
    return router
