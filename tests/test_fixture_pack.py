import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_acceptance", ROOT / "verify_acceptance.py")
VERIFY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFY)


class FixturePackTest(unittest.TestCase):
    def test_manifest_is_complete_and_snapshot_digests_match(self):
        manifest = VERIFY.load_manifest()
        self.assertEqual(9, len(manifest["cases"]))
        self.assertEqual(manifest["required_cases"], [case["id"] for case in manifest["cases"]])

    def test_declared_reports_match_the_public_contract(self):
        manifest = VERIFY.load_manifest()
        for case in manifest["cases"]:
            expected = case["expected"]
            findings = [{**finding, "message": "Synthetic finding"}
                        for finding in expected["findings"]]
            report = {
                "validator": "signalpost_public_citation_v1",
                "valid": expected["valid"],
                "envelopes_checked": expected["envelopes_checked"],
                "citations_checked": expected["citations_checked"],
                "factual_support_verified": False,
                "entity_binding_verified": False,
                "findings": findings,
            }
            VERIFY.check_report(case, report)

    def test_wrong_finding_order_is_rejected(self):
        case = next(
            item for item in VERIFY.load_manifest()["cases"]
            if item["id"] == "bad_url_timestamp_digest"
        )
        report = {
            "validator": "signalpost_public_citation_v1",
            "valid": False,
            "envelopes_checked": 1,
            "citations_checked": 1,
            "factual_support_verified": False,
            "entity_binding_verified": False,
            "findings": [
                {**finding, "message": "Synthetic finding"}
                for finding in reversed(case["expected"]["findings"])
            ],
        }
        with self.assertRaises(VERIFY.AcceptanceFailure):
            VERIFY.check_report(case, report)

    def test_partial_finding_shape_is_rejected(self):
        case = next(
            item for item in VERIFY.load_manifest()["cases"]
            if item["id"] == "missing_citation"
        )
        report = {
            "validator": "signalpost_public_citation_v1",
            "valid": False,
            "envelopes_checked": 1,
            "citations_checked": 0,
            "factual_support_verified": False,
            "entity_binding_verified": False,
            "findings": [{"line": 1, "code": "available_claim_has_no_evidence"}],
        }
        with self.assertRaises(VERIFY.AcceptanceFailure):
            VERIFY.check_report(case, report)

    def test_empty_manifest_fails_closed(self):
        original = VERIFY.MANIFEST_PATH
        try:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "manifest.json"
                path.write_text(json.dumps({"cases": []}), encoding="utf-8")
                VERIFY.MANIFEST_PATH = path
                with self.assertRaises(VERIFY.AcceptanceFailure):
                    VERIFY.load_manifest()
        finally:
            VERIFY.MANIFEST_PATH = original


if __name__ == "__main__":
    unittest.main()
