"""Bounded owner-scoped image evidence. Decoding is not visual understanding."""

import hashlib
import io
import uuid
import warnings

from PIL import Image, UnidentifiedImageError

from .store import (BusinessError, _check_revision, _event, _invalidate, _snapshot,
                    _ticket, connect, stamp)

MAX_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 10_000_000
MEDIA = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def add_evidence(owner: str, ticket_id: str, content: bytes, filename: str,
                 declared_type: str, expected_revision: int) -> dict:
    if not 0 < len(content) <= MAX_BYTES:
        raise BusinessError("EVIDENCE_SIZE_LIMIT", "附件须为 1 字节至 4 MiB。", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                media_type = MEDIA.get(image.format)
                if media_type is None or declared_type != media_type or image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("不支持此图像格式、尺寸或动画")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise BusinessError("INVALID_EVIDENCE_IMAGE", "仅接收可解码、单帧且不超过一千万像素的 PNG/JPEG/WebP。", 422) from exc
    clean_name = filename.replace("\\", "/").split("/")[-1].strip()
    if not clean_name or len(clean_name) > 120 or any(ord(char) < 32 or ord(char) == 127 for char in clean_name):
        raise BusinessError("INVALID_FILENAME", "附件文件名无效或超过 120 字。", 422)
    sha256 = hashlib.sha256(content).hexdigest()
    with connect(write=True) as conn:
        ticket = _ticket(conn, owner, ticket_id)
        existing = conn.execute("SELECT evidence_id FROM evidence WHERE owner=? AND ticket_id=? AND sha256=?", (owner, ticket_id, sha256)).fetchone()
        if existing:
            return {"idempotent_reuse": True, "ticket": _snapshot(conn, owner, ticket_id)}
        _mutable(conn, owner, ticket)
        _check_revision(ticket, expected_revision)
        if len(ticket["attachments"]) >= 5:
            raise BusinessError("EVIDENCE_COUNT_LIMIT", "每张工单最多接入 5 个附件。", 422)
        evidence_id = "EVD-" + uuid.uuid4().hex[:12].upper()
        conn.execute("INSERT INTO evidence(evidence_id,owner,ticket_id,sha256,media_type,filename,size_bytes,content,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (evidence_id, owner, ticket_id, sha256, media_type, clean_name, len(content), content, stamp()))
        _invalidate(conn, owner, ticket_id)
        conn.execute("UPDATE tickets SET revision=revision+1,status='investigating',updated_at=?,evidence_note=CASE WHEN evidence_note='' THEN '客户附件已接入，等待人工核验' ELSE evidence_note END WHERE ticket_id=?", (stamp(), ticket_id))
        _event(conn, owner, ticket_id, "evidence_attached", "interactive_operator", {"evidence_id": evidence_id, "sha256": sha256, "media_type": media_type, "size_bytes": len(content), "analysis": "none"})
        return {"idempotent_reuse": False, "ticket": _snapshot(conn, owner, ticket_id)}


def _mutable(conn, owner, ticket):
    if conn.execute("SELECT 1 FROM movements WHERE owner=? AND ticket_id=?", (owner, ticket["ticket_id"])).fetchone():
        raise BusinessError("TICKET_ALREADY_EXECUTED", "已执行方案的资料保持归档；物流调查使用独立跟进入口。")


def read_evidence(owner: str, evidence_id: str):
    from .store import _owner
    _owner(owner)
    with connect() as conn:
        row = conn.execute("SELECT content,media_type,sha256 FROM evidence WHERE owner=? AND evidence_id=?", (owner, evidence_id)).fetchone()
        if not row:
            raise BusinessError("EVIDENCE_NOT_FOUND", "当前用户没有此附件。", 404)
        return dict(row)


def review_evidence(owner: str, ticket_id: str, evidence_id: str, decision: str,
                    note: str, expected_revision: int) -> dict:
    if decision not in {"accepted", "rejected"} or not note.strip() or len(note) > 1000:
        raise BusinessError("INVALID_EVIDENCE_REVIEW", "需选择接受/不接受，并填写 1–1000 字人工核验说明。", 422)
    with connect(write=True) as conn:
        ticket = _ticket(conn, owner, ticket_id)
        row = conn.execute("SELECT * FROM evidence WHERE owner=? AND ticket_id=? AND evidence_id=?", (owner, ticket_id, evidence_id)).fetchone()
        if row is None:
            raise BusinessError("EVIDENCE_NOT_FOUND", "当前工单没有此附件。", 404)
        if row["review_status"] == decision and row["review_note"] == note.strip():
            return _snapshot(conn, owner, ticket_id)
        _mutable(conn, owner, ticket)
        _check_revision(ticket, expected_revision)
        conn.execute("UPDATE evidence SET review_status=?,review_note=?,reviewed_at=? WHERE evidence_id=?", (decision, note.strip(), stamp(), evidence_id))
        _invalidate(conn, owner, ticket_id)
        conn.execute("UPDATE tickets SET revision=revision+1,status=?,updated_at=? WHERE ticket_id=?", ("investigating" if decision == "accepted" else "manual_review", stamp(), ticket_id))
        _event(conn, owner, ticket_id, "evidence_reviewed", "interactive_admin", {"evidence_id": evidence_id, "decision": decision, "note": note.strip()})
        return _snapshot(conn, owner, ticket_id)
