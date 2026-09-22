import copy
import unittest
from pathlib import Path
from src.provenance import load_record, validate_record, view_for

FIXTURE = Path("fixtures/record.json")


def fresh_record():
    return load_record(FIXTURE)


class RecordRuleTest(unittest.TestCase):
    def test_fixture_passes_all_rules(self):
        record = fresh_record()
        self.assertEqual(record["record_id"], "lzp-0001")
        self.assertEqual(validate_record(record), [])

    def test_history_is_kept_when_judgment_is_overturned(self):
        record = fresh_record()
        old = next(c for c in record["claims"] if c["claim_id"] == "cla-1")
        new = next(c for c in record["claims"] if c["claim_id"] == "cla-2")
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["supersedes"], "cla-1")
        self.assertIsNotNone(old["valid_to"])

    def test_unknown_source_is_rejected(self):
        record = copy.deepcopy(fresh_record())
        record["observations"][0]["source_id"] = "src-999"
        self.assertTrue(any("未登记来源" in p for p in validate_record(record)))

    def test_superseded_claim_must_be_marked(self):
        record = copy.deepcopy(fresh_record())
        for claim in record["claims"]:
            if claim["claim_id"] == "cla-1":
                claim["status"] = "accepted"
        self.assertTrue(any("历史判断须保留并标记失效" in p for p in validate_record(record)))

    def test_superseded_naming_needs_valid_to(self):
        record = copy.deepcopy(fresh_record())
        record["namings"][0]["valid_to"] = None
        self.assertTrue(any("valid_to" in p for p in validate_record(record)))

    def test_same_as_needs_target_record(self):
        record = copy.deepcopy(fresh_record())
        for claim in record["claims"]:
            if claim["claim_id"] == "cla-3":
                del claim["target_record_id"]
        self.assertTrue(any("target_record_id" in p for p in validate_record(record)))

    def test_policy_must_point_to_existing_target(self):
        record = copy.deepcopy(fresh_record())
        record["rights"]["policies"].append(
            {
                "policy_id": "pol-9",
                "applies_to": "cla-999",
                "audience": "public",
                "allowed": True,
                "set_by": "示例博物馆",
            }
        )
        self.assertTrue(any("pol-9" in p for p in validate_record(record)))


class ViewTest(unittest.TestCase):
    def test_public_view_hides_restricted_content(self):
        view = view_for(fresh_record(), "public")
        claim_ids = {c["claim_id"] for c in view["claims"]}
        image_ids = {i["image_id"] for i in view["images"]}
        self.assertNotIn("cla-3", claim_ids)  # 馆方限制的候选关联
        self.assertEqual(image_ids, {"img-1"})  # 未公开图像不可见
        self.assertNotIn("rights", view)  # 策略本身不对公众暴露
        self.assertGreater(len(view["observations"]), 0)  # 授权栏目正常显示

    def test_public_view_keeps_competing_history_when_allowed(self):
        view = view_for(fresh_record(), "public")
        statuses = {c["claim_id"]: c["status"] for c in view["claims"]}
        self.assertEqual(statuses.get("cla-1"), "superseded")
        self.assertEqual(statuses.get("cla-2"), "accepted")

    def test_researcher_sees_competing_hypotheses(self):
        view = view_for(fresh_record(), "researcher")
        claim_ids = {c["claim_id"] for c in view["claims"]}
        self.assertIn("cla-3", claim_ids)
        self.assertIn("cla-4", claim_ids)
        self.assertIn("rights", view)


if __name__ == "__main__":
    unittest.main()
