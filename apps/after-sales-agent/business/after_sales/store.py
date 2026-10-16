"""Transactional demo tickets, immutable proposals, human approvals and execution."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .policy import citation, load_policy
from .scenarios import CUSTOMER, ORDER_ID, catalog, original_order, scenario_order

DATA_KIND = "synthetic_demo_data"


class BusinessError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat()


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def state_dir() -> Path:
    return Path(os.environ.get("AFTER_SALES_DATA_DIR", "/app/after-sales-data"))


def init_store() -> None:
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True)
    key = path / ".identity-key"
    try:
        with key.open("xb") as handle:
            handle.write(secrets.token_bytes(32))
        key.chmod(0o600)
    except FileExistsError:
        pass
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO schema_version VALUES(1);
            CREATE TABLE IF NOT EXISTS orders(
                owner TEXT NOT NULL, order_id TEXT NOT NULL, customer_id TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(owner, order_id));
            CREATE TABLE IF NOT EXISTS tickets(
                ticket_id TEXT PRIMARY KEY, owner TEXT NOT NULL, order_id TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL, reported_at TEXT NOT NULL,
                damage_description TEXT NOT NULL, evidence_note TEXT NOT NULL,
                requested_resolution TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(owner, order_id));
            CREATE TABLE IF NOT EXISTS proposals(
                proposal_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
                owner TEXT NOT NULL, ticket_revision INTEGER NOT NULL, payload TEXT NOT NULL,
                digest TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, review_note TEXT,
                UNIQUE(ticket_id, ticket_revision));
            CREATE TABLE IF NOT EXISTS movements(
                operation_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(proposal_id),
                ticket_id TEXT NOT NULL, owner TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(owner, ticket_id));
            CREATE TABLE IF NOT EXISTS events(
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                ticket_id TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_ticket ON events(owner,ticket_id,event_id);
        """)
    # Serialize startup migration across Gateway workers. Back up the original
    # SQLite snapshot before any additive changes; never re-seed old histories.
    with connect(write=True) as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if version > 2:
            raise RuntimeError("Business schema is newer than this application; startup stopped.")
        if version < 2:
            backup_store("before-schema-v2")
            conn.execute("ALTER TABLE tickets ADD COLUMN case_kind TEXT NOT NULL DEFAULT 'damage'")
            conn.execute("ALTER TABLE tickets ADD COLUMN business_reported_at TEXT")
            conn.execute("UPDATE tickets SET business_reported_at=reported_at WHERE business_reported_at IS NULL")
            conn.execute("CREATE TABLE demo_runs(run_id TEXT PRIMARY KEY,owner TEXT NOT NULL,scenario_id TEXT NOT NULL,order_id TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE evidence(evidence_id TEXT PRIMARY KEY,owner TEXT NOT NULL,ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),sha256 TEXT NOT NULL,media_type TEXT NOT NULL,filename TEXT NOT NULL,size_bytes INTEGER NOT NULL,content BLOB NOT NULL,review_status TEXT NOT NULL DEFAULT 'unverified',review_note TEXT NOT NULL DEFAULT '',reviewed_at TEXT,created_at TEXT NOT NULL,UNIQUE(owner,ticket_id,sha256))")
            conn.execute("CREATE TABLE shipping_followups(followup_id TEXT PRIMARY KEY,owner TEXT NOT NULL,ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),outcome TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(owner,ticket_id))")
            conn.execute("CREATE INDEX evidence_ticket ON evidence(owner,ticket_id)")
            conn.execute("CREATE INDEX tickets_owner_ordering ON tickets(owner,updated_at,ticket_id)")
            conn.execute("INSERT INTO schema_version VALUES(2)")


def backup_store(label: str = "operator") -> str:
    directory = state_dir() / "backups"
    directory.mkdir(exist_ok=True)
    target = directory / (now().strftime("%Y%m%dT%H%M%S%fZ-") + label + ".sqlite3")
    source = sqlite3.connect(state_dir() / "business.sqlite3", timeout=5)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    target.chmod(0o600)
    return str(target)


@contextmanager
def connect(write: bool = False):
    conn = sqlite3.connect(state_dir() / "business.sqlite3", timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower():
            raise BusinessError("DATABASE_BUSY", "业务库暂忙，请稍后读取当前工单再重试。", 503) from exc
        raise
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _owner(owner: str) -> None:
    if not owner or owner == "default" or len(owner) > 128:
        raise BusinessError("IDENTITY_REQUIRED", "需要有效的登录用户身份。", 401)


def _event(conn, owner: str, ticket_id: str, kind: str, actor: str, payload: dict) -> None:
    conn.execute("INSERT INTO events(owner,ticket_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?,?)",
                 (owner, ticket_id, kind, actor, encode(payload), stamp()))


def _demo_order() -> dict:
    return original_order()


def _seed(conn, owner: str) -> None:
    _owner(owner)
    conn.execute("INSERT OR IGNORE INTO orders VALUES(?,?,?,?)", (owner, ORDER_ID, CUSTOMER, encode(_demo_order())))


def _order(conn, owner: str, order_id: str) -> dict:
    _owner(owner)
    row = conn.execute("SELECT payload FROM orders WHERE owner=? AND order_id=? AND customer_id=?",
                       (owner, order_id.strip().upper(), CUSTOMER)).fetchone()
    if not row:
        raise BusinessError("ORDER_NOT_FOUND", "当前演示客户没有此订单。", 404)
    return json.loads(row["payload"])


def get_order(owner: str, order_id: str) -> dict:
    _owner(owner)
    normalized = order_id.strip().upper()
    with connect() as conn:
        row = conn.execute("SELECT payload FROM orders WHERE owner=? AND order_id=?", (owner, normalized)).fetchone()
        order = json.loads(row["payload"]) if row else _demo_order() if normalized == ORDER_ID else None
        if order is None:
            raise BusinessError("ORDER_NOT_FOUND", "当前演示客户没有此订单。", 404)
        existing = conn.execute("SELECT ticket_id,revision,case_kind FROM tickets WHERE owner=? AND order_id=?", (owner, normalized)).fetchone()
        return {"found": True, **order, "existing_ticket": dict(existing) if existing else None}


def create_demo_run(owner: str, scenario_id: str) -> dict:
    _owner(owner)
    run_id = "RUN-" + uuid.uuid4().hex[:12].upper()
    order_id = "DEMO-" + uuid.uuid4().hex[:16].upper()
    try:
        order = scenario_order(scenario_id, order_id, run_id)
    except ValueError as exc:
        raise BusinessError("SCENARIO_NOT_FOUND", str(exc), 404) from exc
    with connect(write=True) as conn:
        conn.execute("INSERT INTO orders VALUES(?,?,?,?)", (owner, order_id, CUSTOMER, encode(order)))
        conn.execute("INSERT INTO demo_runs VALUES(?,?,?,?,?,?)", (run_id, owner, scenario_id, order_id, stamp(), encode(order)))
        _event(conn, owner, run_id, "demo_run_created", "interactive_operator", {"scenario_id": scenario_id, "order_id": order_id, "clock": order["clock"]})
    return {"run_id": run_id, "order": order, "data_kind": DATA_KIND}


def list_demo_runs(owner: str) -> dict:
    _owner(owner)
    with connect() as conn:
        return {"runs": [dict(row) for row in conn.execute("SELECT run_id,scenario_id,order_id,created_at FROM demo_runs WHERE owner=? ORDER BY created_at DESC LIMIT 30", (owner,))], "data_kind": DATA_KIND}


def _ticket(conn, owner: str, ticket_id: str):
    _owner(owner)
    row = conn.execute("SELECT * FROM tickets WHERE owner=? AND ticket_id=?", (owner, ticket_id)).fetchone()
    if not row:
        raise BusinessError("TICKET_NOT_FOUND", "当前用户没有此工单。", 404)
    result = dict(row)
    result["attachments"] = _evidence_metadata(conn, owner, ticket_id)
    return result


def _evidence_metadata(conn, owner: str, ticket_id: str) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT evidence_id,sha256,media_type,filename,size_bytes,review_status,review_note,reviewed_at,created_at FROM evidence WHERE owner=? AND ticket_id=? ORDER BY created_at,evidence_id", (owner, ticket_id))]


def _snapshot(conn, owner: str, ticket_id: str) -> dict:
    result = dict(_ticket(conn, owner, ticket_id))
    result.pop("owner")
    result["order"] = _order(conn, owner, result["order_id"])
    result["data_kind"] = DATA_KIND
    result["proposals"] = []
    for row in conn.execute("SELECT * FROM proposals WHERE owner=? AND ticket_id=? ORDER BY created_at DESC,proposal_id DESC LIMIT 10", (owner, ticket_id)):
        item = dict(row)
        item.pop("owner")
        item["payload"] = json.loads(item["payload"])
        result["proposals"].append(item)
    result["operations"] = [json.loads(row["payload"]) for row in conn.execute(
        "SELECT payload FROM movements WHERE owner=? AND ticket_id=?", (owner, ticket_id))]
    result["events"] = [{"event_id": row["event_id"], "kind": row["kind"], "actor": row["actor"],
                         "created_at": row["created_at"], "payload": json.loads(row["payload"])}
                        for row in conn.execute("SELECT * FROM events WHERE owner=? AND ticket_id=? ORDER BY event_id DESC LIMIT 30", (owner, ticket_id))]
    result["events"].reverse()
    result["history_window"] = {"events": 30, "proposals": 10, "full_audit_url": f"/api/after-sales/tickets/{ticket_id}/events"}
    result["followups"] = [dict(row) for row in conn.execute("SELECT followup_id,outcome,note,created_at FROM shipping_followups WHERE owner=? AND ticket_id=?", (owner, ticket_id))]
    return result


def get_ticket(owner: str, ticket_id: str) -> dict:
    with connect() as conn:
        return _snapshot(conn, owner, ticket_id)


def get_proposal(owner: str, proposal_id: str) -> dict:
    _owner(owner)
    with connect() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE owner=? AND proposal_id=?", (owner, proposal_id)).fetchone()
        if row is None:
            raise BusinessError("PROPOSAL_NOT_FOUND", "当前用户没有此方案。", 404)
        result = dict(row)
        result.pop("owner")
        result["payload"] = json.loads(result["payload"])
        result["data_kind"] = DATA_KIND
        return result


def list_tickets(owner: str, before: str | None = None, limit: int = 30) -> dict:
    _owner(owner)
    with connect() as conn:
        if not 1 <= limit <= 50:
            raise BusinessError("INVALID_LIMIT", "分页大小应为 1–50。", 422)
        clause, parameters = "", [owner]
        if before:
            try:
                cursor_at, cursor_id = before.split("|", 1)
                parsed = datetime.fromisoformat(cursor_at)
                if parsed.tzinfo is None or not cursor_id.startswith("TKT-") or len(cursor_id) > 64:
                    raise ValueError("Invalid cursor")
            except ValueError as exc:
                raise BusinessError("INVALID_CURSOR", "工单分页游标无效，请刷新列表。", 422) from exc
            clause = " AND (updated_at < ? OR (updated_at=? AND ticket_id<?))"
            parameters.extend([cursor_at, cursor_at, cursor_id])
        rows = list(conn.execute("SELECT ticket_id,order_id,status,revision,case_kind,updated_at FROM tickets WHERE owner=?" + clause + " ORDER BY updated_at DESC,ticket_id DESC LIMIT ?", (*parameters, limit + 1)))
        return {"tickets": [dict(row) for row in rows[:limit]], "next_cursor": rows[limit - 1]["updated_at"] + "|" + rows[limit - 1]["ticket_id"] if len(rows) > limit else None, "data_kind": DATA_KIND}


def list_events(owner: str, ticket_id: str, before: int | None = None, limit: int = 30) -> dict:
    if not 1 <= limit <= 100 or (before is not None and before < 1):
        raise BusinessError("INVALID_CURSOR", "审计分页参数无效。", 422)
    with connect() as conn:
        _ticket(conn, owner, ticket_id)
        rows = list(conn.execute("SELECT event_id,kind,actor,payload,created_at FROM events WHERE owner=? AND ticket_id=? AND event_id<? ORDER BY event_id DESC LIMIT ?", (owner, ticket_id, before or 9223372036854775807, limit + 1)))
        return {"events": [{**dict(row), "payload": json.loads(row["payload"])} for row in rows[:limit]], "next_cursor": rows[limit - 1]["event_id"] if len(rows) > limit else None}


def save_damage_report(owner: str, order_id: str, damage_description: str | None = None,
                       evidence_note: str | None = None, requested_resolution: str | None = None,
                       expected_revision: int | None = None) -> dict:
    return _save_report(owner, order_id, damage_description, evidence_note, requested_resolution, expected_revision, "damage")


def save_logistics_report(owner: str, order_id: str, issue_description: str | None = None,
                          evidence_note: str | None = None, expected_revision: int | None = None) -> dict:
    return _save_report(owner, order_id, issue_description, evidence_note, "carrier_inquiry", expected_revision, "logistics")


def _check_revision(ticket, expected_revision: int | None):
    if expected_revision is None or ticket["revision"] != expected_revision:
        raise BusinessError("REVISION_CONFLICT", "请先读取最新工单，并携带其 revision 补充资料。")


def _invalidate(conn, owner: str, ticket_id: str) -> None:
    conn.execute("UPDATE proposals SET status='superseded' WHERE owner=? AND ticket_id=? AND status IN ('pending','approved')", (owner, ticket_id))


def _save_report(owner: str, order_id: str, description: str | None, evidence_note: str | None,
                 requested_resolution: str | None, expected_revision: int | None, case_kind: str) -> dict:
    if requested_resolution not in {None, "", "reship", "refund", "carrier_inquiry"} or (case_kind == "damage" and requested_resolution == "carrier_inquiry"):
        raise BusinessError("INVALID_RESOLUTION", "处理方式只能为 reship、refund 或留空等待补充。", 422)
    if len(description or "") > 2000 or len(evidence_note or "") > 2000:
        raise BusinessError("INPUT_TOO_LONG", "描述和证据说明各不得超过 2000 字。", 422)
    with connect(write=True) as conn:
        _seed(conn, owner)
        order = _order(conn, owner, order_id)
        row = conn.execute("SELECT * FROM tickets WHERE owner=? AND order_id=?", (owner, order["order_id"])).fetchone()
        if row and row["case_kind"] != case_kind:
            raise BusinessError("CASE_KIND_CONFLICT", "此订单已有其他类型工单，请人工协调或创建独立演示实例。")
        old = (row["damage_description"], row["evidence_note"], row["requested_resolution"]) if row else ("", "", "")
        values = tuple(value.strip() if value is not None else old[i] for i, value in enumerate((description, evidence_note, requested_resolution)))
        if row and conn.execute("SELECT 1 FROM movements WHERE owner=? AND ticket_id=?", (owner, row["ticket_id"])).fetchone():
            return _snapshot(conn, owner, row["ticket_id"])
        if row and values == (row["damage_description"], row["evidence_note"], row["requested_resolution"]):
            return _snapshot(conn, owner, row["ticket_id"])
        at = stamp()
        status = "investigating" if all(values) else "awaiting_information"
        if row:
            _check_revision(row, expected_revision)
            ticket_id = row["ticket_id"]
            _invalidate(conn, owner, ticket_id)
            conn.execute("UPDATE tickets SET status=?,revision=revision+1,damage_description=?,evidence_note=?,requested_resolution=?,updated_at=? WHERE owner=? AND ticket_id=?",
                         (status, *values, at, owner, ticket_id))
        else:
            ticket_id = "TKT-" + uuid.uuid4().hex[:12].upper()
            business_at = order.get("clock", {}).get("business_time", at)
            conn.execute("INSERT INTO tickets(ticket_id,owner,order_id,status,revision,reported_at,damage_description,evidence_note,requested_resolution,updated_at,case_kind,business_reported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         (ticket_id, owner, order["order_id"], status, 1, at, *values, at, case_kind, business_at))
        _event(conn, owner, ticket_id, case_kind + "_report_saved", "agent_or_operator",
               {"evidence_kind": "customer_statement_unverified", "status": status, "case_kind": case_kind,
                "changed_fields": {field: {"previous": old[i], "current": values[i]} for i, field in enumerate(("damage_description", "evidence_note", "requested_resolution")) if old[i] != values[i]}})
        return _snapshot(conn, owner, ticket_id)


def _eligibility(ticket, order: dict, policy: dict) -> tuple[list[str], list[str]]:
    missing = [field for field in policy["rules"]["required_fields"] if not ticket[field].strip()]
    reasons = []
    if any(item["review_status"] == "rejected" for item in ticket["attachments"]):
        reasons.append("附件人工审核未通过，需补充说明并交由人工处理")
    reported = datetime.fromisoformat(ticket["business_reported_at"] or ticket["reported_at"])
    if ticket["case_kind"] == "logistics":
        events = order.get("shipping_events", [])
        if order["status"] == "delivered":
            reasons.append("物流显示签收但客户提出异常，需人工核验")
        elif not events:
            reasons.append("没有可核对的物流事件，需人工补充")
        elif order["status"] != "in_transit":
            reasons.append("订单状态不适用停滞调查")
        else:
            latest = max(datetime.fromisoformat(item["occurred_at"]) for item in events)
            if reported - latest < timedelta(hours=policy["rules"]["stalled_after_hours"]):
                reasons.append("申报时最新物流更新尚未超过 72 小时")
        return missing, reasons
    if order["status"] != "delivered" or not order.get("delivered_at"):
        reasons.append("订单尚未签收")
        return missing, reasons
    delivered = datetime.fromisoformat(order["delivered_at"])
    if not delivered <= reported <= delivered + timedelta(days=policy["rules"]["report_window_days"]):
        reasons.append("首次申报时间不在签收后 7 天内")
    if order["paid_amount_minor"] > policy["rules"]["automatic_proposal_amount_cap_minor"]:
        reasons.append("订单金额超过演示方案限额")
    if ticket["requested_resolution"] and ticket["requested_resolution"] not in policy["rules"]["allowed_resolutions"]:
        reasons.append("处理方式不受当前政策支持")
    reported_date = reported.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if reported_date < policy["effective_from"] or (policy["effective_until"] and reported_date > policy["effective_until"]):
        reasons.append("政策不适用于首次申报日期")
    return missing, reasons


def _proposal_payload(ticket, order: dict, policy: dict) -> dict:
    return {
        "ticket_id": ticket["ticket_id"], "ticket_revision": ticket["revision"],
        "order_id": order["order_id"], "customer_id": order["customer_id"],
        "order_sha256": digest(order),
        "resolution": ticket["requested_resolution"], "items": order["items"],
        "refund_amount_minor": order["paid_amount_minor"] if ticket["requested_resolution"] == "refund" else 0,
        "currency": order["currency"], "shipping_target_id": order["shipping_target_id"],
        "evidence_sha256": digest({"description": ticket["damage_description"], "note": ticket["evidence_note"]}),
        "evidence_kind": "customer_statement_unverified", "human_approval_required": True,
        "policy": {"policy_id": policy["policy_id"], "version": policy["version"], "content_sha256": policy["content_sha256"]},
        "citations": [citation(policy, chunk["clause_id"]) for chunk in policy["chunks"]], "data_kind": DATA_KIND,
        "case_kind": ticket["case_kind"], "business_reported_at": ticket["business_reported_at"],
        "clock": order.get("clock", {"mode": "wall_clock"}),
        "attachments_sha256": digest(ticket["attachments"]),
    }


def propose_resolution(owner: str, ticket_id: str) -> dict:
    with connect(write=True) as conn:
        ticket = _ticket(conn, owner, ticket_id)
        if conn.execute("SELECT 1 FROM movements WHERE owner=? AND ticket_id=?", (owner, ticket_id)).fetchone():
            return _snapshot(conn, owner, ticket_id)
        order = _order(conn, owner, ticket["order_id"])
        try:
            policy = _ticket_policy(ticket)
        except ValueError:
            _invalidate(conn, owner, ticket_id)
            conn.execute("UPDATE tickets SET status='manual_review',updated_at=? WHERE ticket_id=?", (stamp(), ticket_id))
            _event(conn, owner, ticket_id, "proposal_blocked", "rules", {"reasons": ["没有唯一适用的政策版本"]})
            return {**_snapshot(conn, owner, ticket_id), "reasons": ["没有唯一适用的政策版本"]}
        if ticket["status"] == "awaiting_followup":
            return _snapshot(conn, owner, ticket_id)
        missing, reasons = _eligibility(ticket, order, policy)
        if missing or reasons:
            status = "awaiting_information" if missing else "manual_review"
            conn.execute("UPDATE proposals SET status='superseded' WHERE owner=? AND ticket_id=? AND status IN ('pending','approved')", (owner, ticket_id))
            conn.execute("UPDATE tickets SET status=?,updated_at=? WHERE ticket_id=?", (status, stamp(), ticket_id))
            _event(conn, owner, ticket_id, "proposal_blocked", "rules", {"missing_fields": missing, "reasons": reasons})
            return {**_snapshot(conn, owner, ticket_id), "missing_fields": missing, "reasons": reasons}
        existing = conn.execute("SELECT * FROM proposals WHERE ticket_id=? AND ticket_revision=?", (ticket_id, ticket["revision"])).fetchone()
        if existing:
            same_payload = digest(_proposal_payload(ticket, order, policy)) == existing["digest"]
            unexpired = datetime.fromisoformat(existing["expires_at"]) >= now()
            if existing["status"] == "rejected" or (existing["status"] in {"pending", "approved"} and same_payload and unexpired):
                return _snapshot(conn, owner, ticket_id)
            # A deliberately requested re-proposal can renew an expired/stale
            # proposal. Keep the old decision and advance the ticket revision.
            conn.execute("UPDATE proposals SET status='superseded' WHERE proposal_id=?", (existing["proposal_id"],))
            conn.execute("UPDATE tickets SET revision=revision+1,status='investigating',updated_at=? WHERE owner=? AND ticket_id=?", (stamp(), owner, ticket_id))
            _event(conn, owner, ticket_id, "proposal_renewed", "rules", {"previous_proposal_id": existing["proposal_id"]})
            ticket = _ticket(conn, owner, ticket_id)
        payload = _proposal_payload(ticket, order, policy)
        proposal_id = "PRP-" + uuid.uuid4().hex[:12].upper()
        expires_at = (now() + timedelta(hours=policy["rules"]["approval_ttl_hours"])).isoformat()
        conn.execute("INSERT INTO proposals(proposal_id,ticket_id,owner,ticket_revision,payload,digest,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (proposal_id, ticket_id, owner, ticket["revision"], encode(payload), digest(payload), "pending", expires_at, stamp()))
        conn.execute("UPDATE tickets SET status='awaiting_approval',updated_at=? WHERE ticket_id=?", (stamp(), ticket_id))
        _event(conn, owner, ticket_id, "proposal_created", "rules", {"proposal_id": proposal_id, "digest": digest(payload)})
        return _snapshot(conn, owner, ticket_id)


def _valid_proposal(conn, owner: str, proposal_id: str, expected_digest: str):
    row = conn.execute("SELECT * FROM proposals WHERE owner=? AND proposal_id=?", (owner, proposal_id)).fetchone()
    if not row:
        raise BusinessError("PROPOSAL_NOT_FOUND", "当前用户没有此方案。", 404)
    if row["digest"] != expected_digest:
        raise BusinessError("PROPOSAL_CHANGED", "方案摘要不匹配，请重新读取后审核。")
    if datetime.fromisoformat(row["expires_at"]) < now():
        raise BusinessError("APPROVAL_EXPIRED", "方案审批有效期已过；重新生成方案并提交人工审批。")
    ticket = _ticket(conn, owner, row["ticket_id"])
    order = _order(conn, owner, ticket["order_id"])
    try:
        policy = _ticket_policy(ticket)
    except ValueError as exc:
        raise BusinessError("POLICY_UNAVAILABLE", str(exc)) from exc
    if digest(json.loads(row["payload"])) != row["digest"]:
        raise BusinessError("PROPOSAL_CORRUPTED", "方案内容与摘要不一致，停止执行并交由人工处理。")
    if ticket["revision"] != row["ticket_revision"] or digest(_proposal_payload(ticket, order, policy)) != row["digest"]:
        raise BusinessError("STALE_PROPOSAL", "工单或政策已变更，需要重新生成方案。")
    missing, reasons = _eligibility(ticket, order, policy)
    if missing or reasons:
        raise BusinessError("RULES_BLOCKED", "当前业务条件不允许执行此方案。")
    return row, ticket


def review_proposal(owner: str, proposal_id: str, expected_digest: str, decision: str, note: str,
                    evidence_confirmed: bool = False) -> dict:
    # Caller must be the interactive admin. This function is never an MCP tool.
    if decision not in {"approve", "reject"} or len(note) > 1000:
        raise BusinessError("INVALID_REVIEW", "审批选择或备注无效。", 422)
    with connect(write=True) as conn:
        proposal, ticket = _valid_proposal(conn, owner, proposal_id, expected_digest)
        if decision == "approve" and (not evidence_confirmed or any(item["review_status"] != "accepted" for item in ticket["attachments"])):
            raise BusinessError("EVIDENCE_REVIEW_REQUIRED", "批准前需确认已核对陈述，并逐一人工审核附件；核验变化后重新生成方案。")
        desired = "approved" if decision == "approve" else "rejected"
        if proposal["status"] == desired:
            return _snapshot(conn, owner, ticket["ticket_id"])
        if proposal["status"] != "pending":
            raise BusinessError("REVIEW_NOT_PENDING", "此方案已经审核或失效。")
        conn.execute("UPDATE proposals SET status=?,reviewed_by=?,reviewed_at=?,review_note=? WHERE proposal_id=?",
                     (desired, owner, stamp(), note.strip(), proposal_id))
        conn.execute("UPDATE tickets SET status=?,updated_at=? WHERE ticket_id=?",
                     ("approved" if decision == "approve" else "manual_review", stamp(), ticket["ticket_id"]))
        _event(conn, owner, ticket["ticket_id"], "human_" + desired, "interactive_admin", {"proposal_id": proposal_id, "note": note.strip(), "evidence_confirmed": evidence_confirmed if decision == "approve" else False})
        return _snapshot(conn, owner, ticket["ticket_id"])


def execute_resolution(owner: str, proposal_id: str) -> dict:
    _owner(owner)
    with connect(write=True) as conn:
        existing = conn.execute("SELECT payload FROM movements WHERE owner=? AND proposal_id=?", (owner, proposal_id)).fetchone()
        if existing:
            return {"idempotent_reuse": True, **json.loads(existing["payload"])}
        row = conn.execute("SELECT digest FROM proposals WHERE owner=? AND proposal_id=?", (owner, proposal_id)).fetchone()
        if not row:
            raise BusinessError("PROPOSAL_NOT_FOUND", "当前用户没有此方案。", 404)
        proposal, ticket = _valid_proposal(conn, owner, proposal_id, row["digest"])
        if proposal["status"] != "approved" or ticket["status"] != "approved" or not proposal["reviewed_by"]:
            raise BusinessError("HUMAN_APPROVAL_REQUIRED", "尚未取得有效人工审批，请在售后工作台审核。")
        payload = json.loads(proposal["payload"])
        result = {
            "operation_id": "OP-" + uuid.uuid4().hex[:12].upper(), "proposal_id": proposal_id,
            "ticket_id": ticket["ticket_id"], "resolution": payload["resolution"],
            "status": "demo_recorded", "created_at": stamp(),
            "refund_amount_minor": payload["refund_amount_minor"], "currency": "CNY",
            "items": payload["items"], "data_kind": DATA_KIND, "case_kind": ticket["case_kind"],
            "external_effect": "none", "message": "已登记演示物流调查，等待人工跟进，没有联系承运方。" if ticket["case_kind"] == "logistics" else "已写入演示业务库，没有真实付款或物流请求。",
        }
        conn.execute("INSERT INTO movements VALUES(?,?,?,?,?,?)", (result["operation_id"], proposal_id, ticket["ticket_id"], owner, encode(result), stamp()))
        conn.execute("UPDATE proposals SET status='executed' WHERE proposal_id=?", (proposal_id,))
        conn.execute("UPDATE tickets SET status=?,updated_at=? WHERE ticket_id=?", ("awaiting_followup" if ticket["case_kind"] == "logistics" else "resolved", stamp(), ticket["ticket_id"]))
        _event(conn, owner, ticket["ticket_id"], "demo_execution_recorded", "approved_executor", result)
        return {"idempotent_reuse": False, **result}


def _ticket_policy(ticket) -> dict:
    at = datetime.fromisoformat(ticket["business_reported_at"] or ticket["reported_at"])
    return load_policy(ticket["case_kind"], at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat())


def get_shipping_events(owner: str, order_id: str) -> dict:
    order = get_order(owner, order_id)
    events = order.get("shipping_events", [])
    if not events and order["status"] == "delivered":
        events = [{"event_id": "ORIGINAL-DELIVERY", "occurred_at": order["delivered_at"], "status": "delivered", "description": "原始演示订单签收记录"}]
    return {"order_id": order["order_id"], "status": order["status"], "events": events, "clock": order.get("clock", {"mode": "wall_clock"}), "data_kind": DATA_KIND}


def record_shipping_followup(owner: str, ticket_id: str, outcome: str, note: str, expected_revision: int) -> dict:
    if outcome not in {"delivered", "manual_review"} or not note.strip() or len(note) > 1000:
        raise BusinessError("INVALID_FOLLOWUP", "需选择演示送达或转人工，并填写 1–1000 字跟进说明。", 422)
    with connect(write=True) as conn:
        ticket = _ticket(conn, owner, ticket_id)
        existing = conn.execute("SELECT outcome,note FROM shipping_followups WHERE owner=? AND ticket_id=?", (owner, ticket_id)).fetchone()
        if existing:
            if existing["outcome"] == outcome and existing["note"] == note.strip():
                return {**_snapshot(conn, owner, ticket_id), "idempotent_reuse": True}
            raise BusinessError("FOLLOWUP_ALREADY_RECORDED", "已保留本次演示跟进结果，不能覆盖历史；待人工状态由人工接管。")
        if ticket["case_kind"] != "logistics" or ticket["status"] != "awaiting_followup":
            raise BusinessError("FOLLOWUP_NOT_PENDING", "仅可跟进已登记的物流调查。")
        _check_revision(ticket, expected_revision)
        followup_id = "FLW-" + uuid.uuid4().hex[:12].upper()
        conn.execute("INSERT INTO shipping_followups VALUES(?,?,?,?,?,?)", (followup_id, owner, ticket_id, outcome, note.strip(), stamp()))
        conn.execute("UPDATE tickets SET status=?,revision=revision+1,updated_at=? WHERE ticket_id=?", ("resolved" if outcome == "delivered" else "manual_review", stamp(), ticket_id))
        _event(conn, owner, ticket_id, "shipping_followup_recorded", "interactive_admin", {"outcome": outcome, "note": note.strip(), "data_kind": DATA_KIND})
        return _snapshot(conn, owner, ticket_id)
