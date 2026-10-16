"""Layer 1: real SQLite/Pillow, isolated state and simulated review identities.

Run with the pinned Gateway interpreter. No Agent/model is constructed.
These simulated reviews do not prove interactive administrator authentication.
"""
import io
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sitecustomize  # also guards this process if not imported during startup
from PIL import Image
from after_sales import store as s
from after_sales.evidence import add_evidence, read_evidence, review_evidence
from after_sales.identity import _signature, verify_call_metadata


class DamageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="after-sales-layer1-")
        self.env = patch.dict(os.environ, {"AFTER_SALES_DATA_DIR": self.temp.name})
        self.env.start()
        s.init_store()
        self.owner = "isolated-owner-a"

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def report(self, scenario="damage-in-window", resolution="reship"):
        order = s.create_demo_run(self.owner, scenario)["order"]
        return s.save_damage_report(self.owner, order["order_id"], "杯体裂纹", "客户文字陈述；隔离测试", resolution)

    def proposal(self, ticket):
        return s.propose_resolution(self.owner, ticket["ticket_id"])["proposals"][0]

    def approve(self, proposal):
        return s.review_proposal(self.owner, proposal["proposal_id"], proposal["digest"], "approve", "模拟管理员，仅工程测试", True)

    def error(self, code, fn, *args):
        with self.assertRaises(s.BusinessError) as caught:
            fn(*args)
        self.assertEqual(code, caught.exception.code)

    def count(self, table):
        with s.connect() as conn:
            return conn.execute("SELECT count(*) FROM " + table).fetchone()[0]

    def test_normal_reship_and_refund_transaction(self):
        for resolution in ("reship", "refund"):
            ticket = self.report(resolution=resolution)
            proposal = self.proposal(ticket)
            self.assertEqual("pending", proposal["status"])
            self.approve(proposal)
            result = s.execute_resolution(self.owner, proposal["proposal_id"])
            self.assertEqual("none", result["external_effect"])
            self.assertEqual(4900 if resolution == "refund" else 0, result["refund_amount_minor"])
            final = s.get_ticket(self.owner, ticket["ticket_id"])
            self.assertEqual("resolved", final["status"])
            self.assertEqual("executed", final["proposals"][0]["status"])
            self.assertEqual(result["operation_id"], final["operations"][0]["operation_id"])
        self.assertEqual(2, self.count("movements"))

    def test_unapproved_execution_has_no_effect(self):
        proposal = self.proposal(self.report())
        self.error("HUMAN_APPROVAL_REQUIRED", s.execute_resolution, self.owner, proposal["proposal_id"])
        self.assertEqual(0, self.count("movements"))

    def test_confirmation_is_required(self):
        proposal = self.proposal(self.report())
        self.error("EVIDENCE_REVIEW_REQUIRED", s.review_proposal, self.owner, proposal["proposal_id"], proposal["digest"], "approve", "", False)
        self.assertEqual("pending", s.get_proposal(self.owner, proposal["proposal_id"])["status"])

    def test_partial_update_and_stale_revision(self):
        ticket = self.report()
        changed = s.save_damage_report(self.owner, ticket["order_id"], None, "新增陈述", None, ticket["revision"])
        self.assertEqual(ticket["damage_description"], changed["damage_description"])
        self.assertEqual("reship", changed["requested_resolution"])
        self.assertEqual(ticket["reported_at"], changed["reported_at"])
        self.assertEqual(ticket["business_reported_at"], changed["business_reported_at"])
        self.error("REVISION_CONFLICT", s.save_damage_report, self.owner, ticket["order_id"], "过期编辑", None, None, ticket["revision"])
        self.assertEqual(changed, s.get_ticket(self.owner, ticket["ticket_id"]))

    def test_clear_missing_fields_blocks_proposal(self):
        ticket = self.report()
        ticket = s.save_damage_report(self.owner, ticket["order_id"], None, "", None, ticket["revision"])
        blocked = s.propose_resolution(self.owner, ticket["ticket_id"])
        self.assertEqual("awaiting_information", blocked["status"])
        self.assertIn("evidence_note", blocked["missing_fields"])
        self.assertEqual([], blocked["proposals"])

    def test_approved_statement_change_invalidates_then_reapproves(self):
        ticket = self.report()
        old = self.proposal(ticket)
        self.approve(old)
        updated = s.save_damage_report(self.owner, ticket["order_id"], None, "补充裂纹位置", None, ticket["revision"])
        self.error("STALE_PROPOSAL", s.execute_resolution, self.owner, old["proposal_id"])
        self.assertEqual("superseded", s.get_proposal(self.owner, old["proposal_id"])["status"])
        self.assertEqual(0, self.count("movements"))
        new = self.proposal(updated)
        self.assertNotEqual(old["digest"], new["digest"])
        self.approve(new)
        s.execute_resolution(self.owner, new["proposal_id"])
        self.assertEqual(1, self.count("movements"))

    @staticmethod
    def image():
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "orange").save(buf, "PNG")
        return buf.getvalue()

    def test_image_change_and_human_review_invalidates(self):
        ticket = self.report()
        old = self.proposal(ticket)
        self.approve(old)
        uploaded = add_evidence(self.owner, ticket["ticket_id"], self.image(), "fixture.png", "image/png", ticket["revision"])["ticket"]
        self.error("STALE_PROPOSAL", s.execute_resolution, self.owner, old["proposal_id"])
        unreviewed = self.proposal(uploaded)
        self.error("EVIDENCE_REVIEW_REQUIRED", self.approve, unreviewed)
        ev = uploaded["attachments"][0]
        reviewed = review_evidence(self.owner, ticket["ticket_id"], ev["evidence_id"], "accepted", "仅确认合成图可打开", uploaded["revision"])
        self.error("STALE_PROPOSAL", s.execute_resolution, self.owner, unreviewed["proposal_id"])
        new = self.proposal(reviewed)
        self.approve(new)
        s.execute_resolution(self.owner, new["proposal_id"])
        self.assertEqual(1, self.count("movements"))

    def test_image_decode_validation_and_duplicate(self):
        ticket = self.report()
        self.error("INVALID_EVIDENCE_IMAGE", add_evidence, self.owner, ticket["ticket_id"], b"not an image", "bad.png", "image/png", 1)
        self.assertEqual(0, self.count("evidence"))
        uploaded = add_evidence(self.owner, ticket["ticket_id"], self.image(), "fixture.png", "image/png", 1)
        duplicate = add_evidence(self.owner, ticket["ticket_id"], self.image(), "fixture.png", "image/png", 1)
        self.assertTrue(duplicate["idempotent_reuse"])
        self.assertEqual(uploaded["ticket"]["revision"], duplicate["ticket"]["revision"])
        self.assertEqual(1, self.count("evidence"))

    def test_repeat_and_concurrent_execution(self):
        ticket = self.report()
        proposal = self.proposal(ticket)
        self.approve(proposal)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: s.execute_resolution(self.owner, proposal["proposal_id"]), range(4)))
        self.assertEqual(1, sum(not r["idempotent_reuse"] for r in results))
        self.assertEqual(1, len({r["operation_id"] for r in results}))
        self.assertEqual(1, self.count("movements"))
        after = s.propose_resolution(self.owner, ticket["ticket_id"])
        self.assertEqual(1, len(after["proposals"]))
        self.assertEqual("resolved", after["status"])

    def test_owner_isolation_across_entities(self):
        ticket = self.report()
        proposal = self.proposal(ticket)
        other = "isolated-owner-b"
        self.error("ORDER_NOT_FOUND", s.get_order, other, ticket["order_id"])
        self.error("TICKET_NOT_FOUND", s.get_ticket, other, ticket["ticket_id"])
        self.error("PROPOSAL_NOT_FOUND", s.get_proposal, other, proposal["proposal_id"])
        self.error("PROPOSAL_NOT_FOUND", s.execute_resolution, other, proposal["proposal_id"])
        self.assertEqual([], s.list_tickets(other)["tickets"])
        uploaded = add_evidence(self.owner, ticket["ticket_id"], self.image(), "fixture.png", "image/png", 1)["ticket"]
        self.error("EVIDENCE_NOT_FOUND", read_evidence, other, uploaded["attachments"][0]["evidence_id"])
        self.assertEqual(0, self.count("movements"))

    def test_exact_original_report_deadline(self):
        deadline = datetime.fromisoformat("2026-10-15T14:30:00+08:00")
        for offset, expected in ((0, "awaiting_approval"), (0.000001, "manual_review")):
            owner = "deadline-" + str(offset)
            with patch.object(s, "now", return_value=deadline + timedelta(seconds=offset)):
                ticket = s.save_damage_report(owner, "ORD-2026-0017", "裂纹", "陈述", "refund")
                self.assertEqual(expected, s.propose_resolution(owner, ticket["ticket_id"])["status"])
                self.assertEqual("2026-10-08T14:30:00+08:00", s.get_order(owner, "ORD-2026-0017")["delivered_at"])

    def test_late_and_high_value_are_manual(self):
        for scenario in ("damage-late", "damage-high-value"):
            ticket = self.report(scenario)
            result = s.propose_resolution(self.owner, ticket["ticket_id"])
            self.assertEqual("manual_review", result["status"])
            self.assertTrue(result["reasons"])
            self.assertEqual([], result["proposals"])

    def test_frozen_business_clock_does_not_extend_approval(self):
        ticket = self.report()
        proposal = self.proposal(ticket)
        self.approve(proposal)
        expiry = datetime.fromisoformat(proposal["expires_at"])
        self.assertGreater(expiry, datetime.now(timezone.utc))
        with patch.object(s, "now", return_value=expiry + timedelta(microseconds=1)):
            self.error("APPROVAL_EXPIRED", s.execute_resolution, self.owner, proposal["proposal_id"])
            renewed = self.proposal(ticket)
            self.assertNotEqual(proposal["proposal_id"], renewed["proposal_id"])
            self.error("HUMAN_APPROVAL_REQUIRED", s.execute_resolution, self.owner, renewed["proposal_id"])
        self.assertEqual(0, self.count("movements"))
        self.assertEqual(ticket["business_reported_at"], s.get_ticket(self.owner, ticket["ticket_id"])["business_reported_at"])

    def test_rejection_needs_new_information(self):
        ticket = self.report()
        proposal = self.proposal(ticket)
        s.review_proposal(self.owner, proposal["proposal_id"], proposal["digest"], "reject", "模拟拒绝")
        self.assertEqual(proposal["proposal_id"], self.proposal(ticket)["proposal_id"])
        self.error("HUMAN_APPROVAL_REQUIRED", s.execute_resolution, self.owner, proposal["proposal_id"])
        self.assertEqual(0, self.count("movements"))

    def test_corrupt_proposal_rolls_back_execution(self):
        proposal = self.proposal(self.report())
        self.approve(proposal)
        with s.connect(write=True) as conn:
            conn.execute("UPDATE proposals SET payload='{}' WHERE proposal_id=?", (proposal["proposal_id"],))
        self.error("PROPOSAL_CORRUPTED", s.execute_resolution, self.owner, proposal["proposal_id"])
        self.assertEqual(0, self.count("movements"))

    def test_replay_preserves_prior_history(self):
        first = self.report()
        second = self.report()
        self.assertNotEqual(first["order_id"], second["order_id"])
        self.assertEqual(first, s.get_ticket(self.owner, first["ticket_id"]))
        self.assertEqual(2, self.count("demo_runs"))

    def test_audit_cursor_has_no_duplicates(self):
        ticket = self.report()
        for index in range(35):
            ticket = s.save_damage_report(self.owner, ticket["order_id"], None, str(index), None, ticket["revision"])
        ids, cursor = [], None
        while True:
            page = s.list_events(self.owner, ticket["ticket_id"], cursor, 7)
            ids.extend(e["event_id"] for e in page["events"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(36, len(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(30, len(ticket["events"]))

    def test_signature_uses_wall_clock_and_rejects_bad_metadata(self):
        import time
        issued = str(int(time.time()))
        headers = {"x-after-sales-user": self.owner, "x-after-sales-issued": issued,
                   "x-after-sales-signature": _signature(self.owner, issued)}
        context = lambda h: SimpleNamespace(request_context=SimpleNamespace(meta={"headers": h}))
        self.assertEqual(self.owner, verify_call_metadata(context(headers)))
        for invalid in ({}, {**headers, "x-after-sales-user": "other"},
                        {**headers, "x-after-sales-issued": str(int(issued) - 61)},
                        {**headers, "x-after-sales-signature": "bad"}):
            self.error("IDENTITY_REQUIRED", verify_call_metadata, context(invalid))

    def test_verification_process_blocks_remote_network(self):
        import socket
        with socket.socket() as sock:
            with self.assertRaisesRegex(RuntimeError, "remote network access denied"):
                sock.connect(("198.51.100.1", 443))


if __name__ == "__main__":
    unittest.main(verbosity=2)
