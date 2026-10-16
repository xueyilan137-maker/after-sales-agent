"""Image boundaries on isolated SQLite/Pillow; no vision or real admin claims."""
import io
from unittest.mock import patch

from PIL import Image
import test_damage as damage
from after_sales import evidence as e
from after_sales import store as s


class EvidenceTests(damage.DamageTests):
    # Reuse fixtures without rerunning the inherited damage suite.
    @staticmethod
    def picture(fmt="PNG", color="orange", frames=False):
        out = io.BytesIO()
        image = Image.new("RGB", (16, 16), color)
        kwargs = {"save_all": True, "append_images": [Image.new("RGB", (16, 16), "blue")]} if frames else {}
        image.save(out, fmt, **kwargs)
        return out.getvalue()

    def test_formats_hash_readback_and_filename(self):
        import hashlib
        ticket = self.report()
        for fmt, media in e.MEDIA.items():
            data = self.picture(fmt)
            ticket = e.add_evidence(self.owner, ticket["ticket_id"], data, "folder\\fixture." + fmt.lower(), media, ticket["revision"])["ticket"]
            item = ticket["attachments"][-1]
            read = e.read_evidence(self.owner, item["evidence_id"])
            self.assertEqual(data, read["content"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), read["sha256"])
            self.assertEqual(media, read["media_type"])
            self.assertNotIn("\\", item["filename"])

    def test_rejected_inputs_never_mutate_ticket(self):
        ticket = self.report()
        data = self.picture()
        samples = [("EVIDENCE_SIZE_LIMIT", b"", "x.png", "image/png"),
                   ("EVIDENCE_SIZE_LIMIT", b"x" * (e.MAX_BYTES + 1), "x.png", "image/png"),
                   ("INVALID_EVIDENCE_IMAGE", data, "x.png", "image/jpeg"),
                   ("INVALID_EVIDENCE_IMAGE", self.picture("GIF"), "x.gif", "image/gif"),
                   ("INVALID_EVIDENCE_IMAGE", self.picture(frames=True), "x.png", "image/png"),
                   ("INVALID_EVIDENCE_IMAGE", data[:30], "x.png", "image/png"),
                   ("INVALID_FILENAME", data, "bad\n.png", "image/png")]
        for code, payload, name, media in samples:
            with self.subTest(code=code, name=name, size=len(payload)):
                self.error(code, e.add_evidence, self.owner, ticket["ticket_id"], payload, name, media, ticket["revision"])
                self.assertEqual(ticket, s.get_ticket(self.owner, ticket["ticket_id"]))
        with patch.object(e, "MAX_PIXELS", 255):
            self.error("INVALID_EVIDENCE_IMAGE", e.add_evidence, self.owner, ticket["ticket_id"], data, "x.png", "image/png", ticket["revision"])
        self.assertEqual(0, self.count("evidence"))

    def test_count_revision_and_review_rejection(self):
        ticket = self.report()
        original = ticket
        for index in range(5):
            ticket = e.add_evidence(self.owner, ticket["ticket_id"], self.picture(color=(index, 20, 30)), "x.png", "image/png", ticket["revision"])["ticket"]
        self.error("EVIDENCE_COUNT_LIMIT", e.add_evidence, self.owner, ticket["ticket_id"], self.picture(color="red"), "six.png", "image/png", ticket["revision"])
        item = ticket["attachments"][0]
        self.error("REVISION_CONFLICT", e.review_evidence, self.owner, ticket["ticket_id"], item["evidence_id"], "accepted", "test", original["revision"])
        rejected = e.review_evidence(self.owner, ticket["ticket_id"], item["evidence_id"], "rejected", "合成图片不能证明损坏", ticket["revision"])
        self.assertEqual("manual_review", rejected["status"])
        repeated = e.review_evidence(self.owner, ticket["ticket_id"], item["evidence_id"], "rejected", "合成图片不能证明损坏", ticket["revision"])
        self.assertEqual(rejected, repeated)
        self.assertEqual(original["reported_at"], rejected["reported_at"])
        self.assertEqual(original["business_reported_at"], rejected["business_reported_at"])
        self.assertEqual(0, self.count("movements"))


# Inheritance supplies helpers, but existing tests belong to test_damage.py.
for _name in list(vars(damage.DamageTests)):
    if _name.startswith("test_"):
        setattr(EvidenceTests, _name, None)
