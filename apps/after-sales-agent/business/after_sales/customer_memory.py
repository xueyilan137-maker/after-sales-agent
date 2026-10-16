"""Confirmed preferences through the pinned DeerMem CRUD contract, no LLM."""

import json
import threading

from .store import BusinessError, _owner, connect, digest, encode, stamp, state_dir

_manager = None
_lock = threading.Lock()
AGENT_BUCKET = "after-sales"
ALLOWED_VALUES = {"language": {"zh-CN", "en"}, "contact_channel": {"in_app"},
                  "resolution_preference": {"ask_each_time", "refund", "reship"}}


def manager():
    global _manager
    with _lock:
        if _manager is None:
            from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
            # Direct public backend construction avoids the host factory's
            # default-model injection. No passive add/add_nowait/warm call.
            _manager = DeerMem.from_config({"storage_path": str(state_dir() / "customer-memory"),
                                            "strict_user_scope": True, "retrieval_adapter": "",
                                            "token_counting": "char", "max_facts": 100, "model": {}}, mode="tool")
    return _manager


def close_memory():
    global _manager
    with _lock:
        if _manager is not None:
            _manager.close()
            _manager = None


def _facts(owner: str) -> list[dict]:
    _owner(owner)
    try:
        raw = manager().get_memory(user_id=owner, agent_name=AGENT_BUCKET)
    except Exception as exc:
        raise BusinessError("MEMORY_UNAVAILABLE", "客户记忆暂不可读，请使用本轮已提供信息。", 503) from exc
    result = []
    for fact in raw.get("facts", []):
        # Pinned DeerMem normalizes custom categories to `other` while
        # preserving their name in categoryExtension. Accept both its durable
        # representation and the historical unnormalized document shape.
        if not (fact.get("category") == "confirmed_preference" or
                (fact.get("category") == "other" and fact.get("categoryExtension") == "confirmed_preference")):
            continue
        try:
            record = json.loads(fact["content"])
            if record.get("key") not in ALLOWED_VALUES or record.get("value") not in ALLOWED_VALUES[record["key"]]:
                continue
            result.append({"fact_id": fact["id"], **record, "digest": digest(record)})
        except (ValueError, KeyError, TypeError):
            continue
    return result


def get_customer_memory(owner: str) -> dict:
    return {"preferences": _facts(owner), "backend": "DeerFlow.DeerMem", "capture": "interactive_confirmation_only",
            "authority": "preference_not_business_fact", "auto_extraction": False,
            "data_kind": "synthetic_demo_data",
            "message": "偏好仅供沟通参考；本次退款/补发仍需客户确认，订单、审批和执行查业务库。"}


def save_preference(owner: str, key: str, value: str, source_note: str, expected_digest: str | None = None) -> dict:
    _owner(owner)
    if key not in ALLOWED_VALUES or value not in ALLOWED_VALUES[key] or not source_note.strip() or len(source_note) > 500:
        raise BusinessError("INVALID_MEMORY", "请选择支持的偏好，并填写 1–500 字人工确认来源。", 422)
    # Cold backend imports/initialization can exceed SQLite's busy timeout.
    # Construct under the manager lock before taking the business write lock;
    # preference read/modify/write remains serialized below.
    try:
        backend = manager()
    except Exception as exc:
        raise BusinessError("MEMORY_WRITE_UNAVAILABLE", "记忆后端暂不可用，请稍后重新读取。", 503) from exc
    # Serialize the business adapter's read/modify/write across processes. The
    # canonical memory stays in DeerMem; this lock is not a second memory DB.
    with connect(write=True):
        existing = next((fact for fact in _facts(owner) if fact["key"] == key), None)
        if existing and existing["value"] == value and existing["source_note"] == source_note.strip():
            return get_customer_memory(owner)
        if existing and expected_digest != existing["digest"]:
            raise BusinessError("MEMORY_CONFLICT", "偏好已变更，请读取当前记忆后再纠正。")
        if not existing and expected_digest is not None:
            raise BusinessError("MEMORY_CONFLICT", "此偏好已被遗忘，请重新读取。")
        record = {"key": key, "value": value, "source_kind": "interactive_operator_confirmation",
                  "source_note": source_note.strip(), "confirmed_at": stamp(),
                  "revision": existing["revision"] + 1 if existing else 1,
                  "previous_digest": existing["digest"] if existing else None}
        try:
            if existing:
                backend.update_fact(existing["fact_id"], content=encode(record), category="confirmed_preference", confidence=1.0, user_id=owner, agent_name=AGENT_BUCKET)
            else:
                _, fact_id = backend.create_fact(encode(record), category="confirmed_preference", confidence=1.0, user_id=owner, agent_name=AGENT_BUCKET)
                if fact_id is None:
                    raise BusinessError("MEMORY_CAPACITY", "记忆容量不足，此偏好未保存。")
            result = get_customer_memory(owner)
            saved = next((fact for fact in result["preferences"] if fact["key"] == key), None)
            if saved is None or saved["digest"] != digest(record):
                raise BusinessError("MEMORY_WRITE_UNAVAILABLE", "偏好写后回读不一致，请重新读取后再决定是否重试。", 503)
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("MEMORY_WRITE_UNAVAILABLE", "记忆写入未确认，请重新读取当前记忆再决定是否重试。", 503) from exc
    return result


def forget_preference(owner: str, fact_id: str, expected_digest: str) -> dict:
    _owner(owner)
    try:
        backend = manager()
    except Exception as exc:
        raise BusinessError("MEMORY_WRITE_UNAVAILABLE", "记忆后端暂不可用，请稍后重新读取。", 503) from exc
    with connect(write=True):
        fact = next((fact for fact in _facts(owner) if fact["fact_id"] == fact_id), None)
        if not fact:
            return get_customer_memory(owner)
        if expected_digest != fact["digest"]:
            raise BusinessError("MEMORY_CONFLICT", "偏好已变更，请读取后再遗忘。")
        try:
            backend.delete_fact(fact_id, user_id=owner, agent_name=AGENT_BUCKET)
            result = get_customer_memory(owner)
            if any(item["fact_id"] == fact_id for item in result["preferences"]):
                raise BusinessError("MEMORY_WRITE_UNAVAILABLE", "遗忘写后回读仍存在，请重新读取后再决定是否重试。", 503)
        except BusinessError:
            raise
        except Exception as exc:
            raise BusinessError("MEMORY_WRITE_UNAVAILABLE", "遗忘操作未确认，请重新读取当前记忆。", 503) from exc
    return result
