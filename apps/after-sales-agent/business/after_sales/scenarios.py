"""Immutable replay definitions. A replay creates a new order, never edits history."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

DATA_KIND = "synthetic_demo_data"
CUSTOMER = "DEMO-CUSTOMER-01"
ORDER_ID = "ORD-2026-0017"


def original_order() -> dict:
    # The P1 identity and delivery timestamp are deliberately kept unchanged.
    return {
        "order_id": ORDER_ID, "customer_id": CUSTOMER, "status": "delivered",
        "items": [{"sku": "MUG-CERAMIC-WHITE", "name": "白色陶瓷马克杯（演示商品）", "quantity": 1}],
        "delivered_at": "2026-10-08T14:30:00+08:00", "paid_amount_minor": 4900,
        "currency": "CNY", "shipping_target_id": "DEMO-DELIVERY-001", "data_kind": DATA_KIND,
    }


def catalog() -> dict:
    return json.loads((Path(__file__).parent / "data/scenarios.json").read_text(encoding="utf-8"))


def scenario_order(scenario_id: str, order_id: str, run_id: str) -> dict:
    definitions = catalog()
    scenario = next((item for item in definitions["scenarios"] if item["scenario_id"] == scenario_id), None)
    if scenario is None:
        raise ValueError("演示场景不存在。")
    order = deepcopy(original_order())
    order.update(scenario["order"])
    order.update({"order_id": order_id, "demo_run_id": run_id, "scenario_id": scenario_id,
                  "scenario_catalog_version": definitions["version"],
                  "scenario_sha256": hashlib.sha256(json.dumps(scenario, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                  "clock": {"mode": "frozen_synthetic", "business_time": scenario["business_time"],
                            "purpose": "仅用于合成业务期限；审批和身份过期使用真实 UTC 时钟"}})
    return order
