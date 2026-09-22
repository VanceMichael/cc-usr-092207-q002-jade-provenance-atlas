import copy
import json
import unittest
from pathlib import Path

from src.claims import (
    active_claims,
    add_claim,
    add_identity_link,
    claim_history,
    decide_identity_link,
    new_store,
    public_view,
    retract_claim,
    supersede_claim,
    validate_store,
)

FIXTURE = Path("fixtures/claims.json")


def load_store():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_claim(claim_id, **overrides):
    claim = {
        "claim_id": claim_id,
        "subject": "artifact:LZ-CONG-0001",
        "predicate": "dated_to",
        "value": "良渚文化中期",
        "source": {"kind": "publication", "ref": "某研究"},
        "proposer": "researcher:RX-99",
        "proposed_at": "2026",
        "confidence": "medium",
        "valid_from": "2026",
        "valid_to": None,
        "status": "active",
        "superseded_by": None,
        "visibility": "public",
    }
    claim.update(overrides)
    return claim


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = load_store()

    def test_fixture_validates(self):
        validate_store(self.store)

    def test_supersede_keeps_old_catalogue_name(self):
        history = claim_history(self.store, subject="artifact:LZ-CONG-0001",
                                predicate="has_name")
        self.assertEqual([c["value"] for c in history], ["周玉琮", "良渚文化玉琮"])
        self.assertEqual(history[0]["status"], "superseded")
        self.assertEqual(history[0]["superseded_by"], "c-0003")
        names = active_claims(self.store, predicate="has_name")
        self.assertEqual([c["value"] for c in names], ["良渚文化玉琮"])

    def test_competing_datings_coexist(self):
        datings = active_claims(self.store, subject="artifact:LZ-CONG-0001",
                                predicate="dated_to")
        self.assertEqual(len(datings), 2)
        self.assertEqual({c["proposer"] for c in datings},
                         {"researcher:RY-02", "researcher:RX-11"})

    def test_supersede_marks_old_and_keeps_it(self):
        store = new_store()
        add_claim(store, make_claim("c-1", value="周汉", proposed_at="1923"))
        supersede_claim(store, "c-1", make_claim("c-2", value="良渚文化晚期"))
        self.assertEqual(len(store["claims"]), 2)
        old = store["claims"][0]
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["superseded_by"], "c-2")
        self.assertEqual(old["valid_to"], "2026")
        validate_store(store)

    def test_superseded_or_retracted_claims_are_frozen(self):
        store = new_store()
        add_claim(store, make_claim("c-1"))
        supersede_claim(store, "c-1", make_claim("c-2"))
        with self.assertRaises(ValueError):
            supersede_claim(store, "c-1", make_claim("c-3"))
        with self.assertRaises(ValueError):
            retract_claim(store, "c-1")
        retract_claim(store, "c-2")
        with self.assertRaises(ValueError):
            supersede_claim(store, "c-2", make_claim("c-4"))

    def test_rejected_identity_link_remains_on_record(self):
        links = {l["link_id"]: l for l in self.store["identity_links"]}
        self.assertEqual(links["L-0002"]["link_status"], "rejected")
        self.assertEqual(links["L-0002"]["decided_by"], "researcher:RY-02")

    def test_identity_link_decided_only_once(self):
        store = new_store()
        add_identity_link(store, {
            "link_id": "L-1",
            "artifact_a": "artifact:甲",
            "artifact_b": "artifact:乙",
            "link_status": "candidate",
            "rationale": "尺寸相近",
            "proposer": "researcher:RY-02",
            "proposed_at": "2026",
            "visibility": "public",
        })
        decide_identity_link(store, "L-1", "accepted", "researcher:RX-11", "2026-09")
        with self.assertRaises(ValueError):
            decide_identity_link(store, "L-1", "rejected", "researcher:RX-11", "2026-10")

    def test_public_view_hides_restricted_and_internal(self):
        view = public_view(self.store)
        self.assertTrue(all(c["visibility"] == "public" for c in view["claims"]))
        subjects = {c["claim_id"] for c in view["claims"]}
        self.assertNotIn("c-0008", subjects)  # 未公开检修报告
        self.assertNotIn("c-0009", subjects)  # 未授权公开的旧藏人
        # 被取代的旧定名是 public，公众仍能看到定名沿革
        self.assertIn("c-0001", subjects)

    def test_every_claim_traceable(self):
        for claim in self.store["claims"]:
            self.assertTrue(claim["source"]["ref"])
            self.assertTrue(claim["proposer"])
            self.assertTrue(claim["proposed_at"])
        with self.assertRaises(ValueError):
            add_claim(new_store(), make_claim("c-1", proposer=""))

    def test_duplicate_claim_id_rejected(self):
        store = new_store()
        add_claim(store, make_claim("c-1"))
        with self.assertRaises(ValueError):
            add_claim(store, make_claim("c-1"))

    def test_store_copy_isolation(self):
        snapshot = copy.deepcopy(self.store)
        supersede_claim(self.store, "c-0004", make_claim("c-9999"))
        self.assertNotEqual(self.store, snapshot)


if __name__ == "__main__":
    unittest.main()
