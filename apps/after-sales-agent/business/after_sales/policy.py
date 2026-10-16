"""Versioned Markdown chunks and local lexical retrieval (no embedding bill)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(__file__).parent / "data"


MANIFESTS = {"damage": ["policies.json"], "logistics": ["logistics-demo-v1.json"]}


def _read_policy(manifest: str) -> dict:
    policy = json.loads((DATA_DIR / manifest).read_text(encoding="utf-8"))
    text = (DATA_DIR / policy["document"]).read_text(encoding="utf-8")
    # Rules and prose form one immutable effective policy identity.
    policy["content_sha256"] = hashlib.sha256(
        (json.dumps(policy, ensure_ascii=False, sort_keys=True) + "\n" + text).encode()
    ).hexdigest()
    policy["text"] = text
    policy["chunks"] = [
        {"clause_id": match[1], "title": match[2].strip(), "text": match[3].strip()}
        for match in re.finditer(r"(?ms)^## ((?:DAMAGE|LOGISTICS)-\d+) ([^\n]+)\n(.*?)(?=^## |\Z)", text)
    ]
    return policy


def effective_date(as_of: str | None = None) -> str:
    if as_of is None:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    return date.fromisoformat(as_of).isoformat()


def load_policy(case_kind: str = "damage", as_of: str | None = None,
                policy_id: str | None = None, version: str | None = None) -> dict:
    if case_kind not in MANIFESTS:
        raise ValueError("业务类型只能为 damage 或 logistics。")
    policies = [_read_policy(manifest) for manifest in MANIFESTS[case_kind]]
    if policy_id:
        matches = [p for p in policies if p["policy_id"] == policy_id and (version is None or p["version"] == version)]
    else:
        selected_date = effective_date(as_of)
        matches = [p for p in policies if p["effective_from"] <= selected_date and
                   (not p["effective_until"] or selected_date <= p["effective_until"])]
    if len(matches) != 1:
        raise ValueError("没有唯一适用的政策版本，需要人工处理。")
    return matches[0]


def citation(policy: dict, clause_id: str) -> dict:
    return {
        "policy_id": policy["policy_id"], "version": policy["version"],
        "clause_id": clause_id, "content_sha256": policy["content_sha256"],
        "source": f"/api/after-sales/policies/{policy['policy_id']}?version={policy['version']}#{clause_id}",
        "data_kind": "synthetic_demo_data",
    }


def terms(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9_-]+", text.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(segment[i:i + 2] for i in range(len(segment) - 1))
    return result


def search_policy(query: str, top_k: int = 3, as_of: str | None = None, case_kind: str = "damage") -> dict:
    if not query.strip() or len(query) > 500 or not 1 <= top_k <= 5:
        raise ValueError("政策查询须为 1–500 字，top_k 为 1–5。")
    if case_kind not in MANIFESTS:
        raise ValueError("业务类型只能为 damage 或 logistics。")
    selected_date = effective_date(as_of)
    try:
        policy = load_policy(case_kind, selected_date)
    except ValueError:
        return {"retrieval": "local_lexical_bigram_v1", "matches": [], "active_policy": False,
                "as_of": selected_date, "data_kind": "synthetic_demo_data", "reason": "没有唯一适用政策，请转人工。"}
    matches = []
    wanted = terms(query)
    for chunk in policy["chunks"]:
        score = len(wanted & terms(chunk["title"] + " " + chunk["text"]))
        if score:
            matches.append({**chunk, "score": score, "citation": citation(policy, chunk["clause_id"])})
    matches.sort(key=lambda item: (-item["score"], item["clause_id"]))
    return {"retrieval": "local_lexical_bigram_v1", "matches": matches[:top_k],
            "data_kind": "synthetic_demo_data", "active_policy": True, "as_of": selected_date,
            "case_kind": case_kind, "policy_version": policy["version"]}


def case_document(case_id: str) -> dict:
    cases = json.loads((DATA_DIR / "knowledge-cases.json").read_text(encoding="utf-8"))
    return next(item for item in cases["cases"] if item["case_id"] == case_id)


def search_knowledge(query: str, case_kind: str = "damage", as_of: str | None = None, top_k: int = 3) -> dict:
    result = search_policy(query, top_k, as_of, case_kind)
    examples = json.loads((DATA_DIR / "knowledge-cases.json").read_text(encoding="utf-8"))
    wanted = terms(query)
    matches = []
    for item in examples["cases"]:
        score = len(wanted & terms(item["title"] + " " + item["text"]))
        if item["case_kind"] == case_kind and score:
            matches.append({**item, "score": score, "source": f"/api/after-sales/cases/{item['case_id']}",
                            "data_kind": examples["data_kind"], "authority": "illustration_only_not_execution_evidence"})
    matches.sort(key=lambda item: (-item["score"], item["case_id"]))
    return {**result, "cases": matches[:top_k], "case_catalog_version": examples["version"]}
