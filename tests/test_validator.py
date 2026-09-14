"""Focused unit tests for the citation validator library.

All fixtures are synthetic and created in temporary directories. No test makes
a network request; the last test proves the validator runs with sockets
disabled.
"""

import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from signalpost_citation_validator import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    VALIDATOR_ID,
    validate_envelope,
    validate_input,
)


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SnapshotTestCase(unittest.TestCase):
    """Base that provides a temporary snapshot root and helper."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "snapshots-root"
        self.root.mkdir()

    def write_snapshot(self, relative: str, data: bytes) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return relative

    def evidence(self, relative: str, data: bytes, **overrides):
        record = {
            "id": "ev-1",
            "source_url": "https://example.org/source",
            "retrieved_at": "2026-09-12T10:30:00Z",
            "content_sha256": digest_of(data),
            "snapshot_path": relative,
        }
        record.update(overrides)
        return record

    def envelope(self, claims, evidence):
        return {
            "organisation_number": "123456789",
            "claims": claims,
            "evidence": evidence,
        }

    def available_claim(self, evidence_ids=("ev-1",), value="synthetic-value"):
        return {
            "field": "synthetic_field",
            "value": value,
            "availability": "available",
            "evidence_ids": list(evidence_ids),
        }

    def codes(self, result):
        return [finding["code"] for finding in result.findings]


class ValidEnvelopeTests(SnapshotTestCase):
    def test_valid_available_claim_with_matching_snapshot(self):
        data = b"Synthetic snapshot bytes for the valid case.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()], [self.evidence(relative, data)]
        )
        result = validate_envelope(envelope, self.root)
        self.assertTrue(result.valid)
        self.assertEqual([], result.findings)
        self.assertEqual(1, result.citations_checked)

    def test_zero_false_and_empty_list_values_are_not_missing(self):
        data = b"Synthetic fixture for zero, false and empty-list values.\n"
        relative = self.write_snapshot("source.txt", data)
        claims = [
            {"field": "synthetic_count", "value": 0, "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "synthetic_flag", "value": False, "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "synthetic_items", "value": [], "availability": "available", "evidence_ids": ["ev-1"]},
            {"field": "synthetic_unavailable", "value": None, "availability": "not_available", "evidence_ids": []},
        ]
        envelope = self.envelope(claims, [self.evidence(relative, data)])
        result = validate_envelope(envelope, self.root)
        self.assertTrue(result.valid)
        self.assertEqual([], result.findings)
        # One distinct evidence ID reused across three claims counts once.
        self.assertEqual(1, result.citations_checked)
        for claim in claims:
            self.assertIn(claim["value"], (0, False, [], None))

    def test_not_available_claim_without_evidence_is_accepted(self):
        claim = {"field": "synthetic_field", "value": None, "availability": "not_available", "evidence_ids": []}
        result = validate_envelope(self.envelope([claim], []), self.root)
        self.assertTrue(result.valid)
        self.assertEqual(0, result.citations_checked)

    def test_snapshot_digest_is_computed_not_hardcoded(self):
        data = bytes(range(256))
        relative = self.write_snapshot("binary-source.bin", data)
        envelope = self.envelope(
            [self.available_claim()], [self.evidence(relative, data)]
        )
        self.assertTrue(validate_envelope(envelope, self.root).valid)

    def test_citations_checked_counts_distinct_ids_per_envelope(self):
        data = b"Shared synthetic snapshot.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [
                self.available_claim(["ev-1"]),
                self.available_claim(["ev-1", "ev-2"]),
                self.available_claim(["ev-2"]),
            ],
            [
                self.evidence(relative, data, id="ev-1"),
                self.evidence(relative, data, id="ev-2"),
            ],
        )
        result = validate_envelope(envelope, self.root)
        self.assertEqual(2, result.citations_checked)


class ClaimAndEvidenceTests(SnapshotTestCase):
    def test_available_claim_without_evidence_is_rejected(self):
        envelope = self.envelope([self.available_claim([])], [])
        result = validate_envelope(envelope, self.root)
        self.assertEqual(["available_claim_has_no_evidence"], self.codes(result))
        finding = result.findings[0]
        self.assertIsNone(finding["evidence_id"])
        self.assertEqual(0, finding["claim_index"])

    def test_missing_evidence_record_is_rejected(self):
        envelope = self.envelope([self.available_claim(["ev-ghost"])], [])
        result = validate_envelope(envelope, self.root)
        self.assertEqual(["missing_evidence_record"], self.codes(result))
        self.assertEqual("ev-ghost", result.findings[0]["evidence_id"])
        # A cited ID counts even when its record is missing.
        self.assertEqual(1, result.citations_checked)

    def test_duplicate_evidence_ids_are_rejected(self):
        data = b"Duplicate declaration fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [],
            [self.evidence(relative, data), self.evidence(relative, data)],
        )
        result = validate_envelope(envelope, self.root)
        self.assertEqual(["duplicate_evidence_id"], self.codes(result))
        self.assertIsNone(result.findings[0]["claim_index"])
        self.assertEqual("ev-1", result.findings[0]["evidence_id"])

    def test_line_number_is_preserved_in_findings(self):
        envelope = self.envelope([self.available_claim([])], [])
        result = validate_envelope(envelope, self.root, line=7)
        self.assertEqual(7, result.findings[0]["line"])


class EvidenceMetadataTests(SnapshotTestCase):
    def test_non_http_url_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        for url in ("file:///synthetic/source.txt", "ftp://example.org/source", "not a url"):
            envelope = self.envelope(
                [self.available_claim()], [self.evidence(relative, data, source_url=url)]
            )
            self.assertEqual(["invalid_source_url"], self.codes(validate_envelope(envelope, self.root)), url)

    def test_url_with_embedded_credentials_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence(relative, data, source_url="https://user:secret@example.org/source")],
        )
        self.assertEqual(["invalid_source_url"], self.codes(validate_envelope(envelope, self.root)))

    def test_url_with_ascii_control_or_whitespace_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        for url in (
            "https://example.org/\nfoo",
            "https://example.org/foo bar",
            "https://example.org/foo\tbar",
            "https://example.org/foo\rbar",
            "https://example.org/\x00foo",
            "https://example.org/foo\x7fbar",
        ):
            envelope = self.envelope(
                [self.available_claim()], [self.evidence(relative, data, source_url=url)]
            )
            self.assertEqual(
                ["invalid_source_url"],
                self.codes(validate_envelope(envelope, self.root)),
                url,
            )

    def test_percent_encoded_space_in_url_is_accepted(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence(relative, data, source_url="https://example.org/foo%20bar")],
        )
        self.assertTrue(validate_envelope(envelope, self.root).valid)

    def test_url_with_invalid_port_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        for url in (
            "https://example.org:abc/source",
            "https://example.org:65536/source",
            "https://example.org:80x/source",
        ):
            envelope = self.envelope(
                [self.available_claim()], [self.evidence(relative, data, source_url=url)]
            )
            self.assertEqual(
                ["invalid_source_url"],
                self.codes(validate_envelope(envelope, self.root)),
                url,
            )

    def test_url_with_valid_port_is_accepted(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence(relative, data, source_url="https://example.org:443/source")],
        )
        self.assertTrue(validate_envelope(envelope, self.root).valid)

    def test_timezone_free_timestamp_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence(relative, data, retrieved_at="2026-09-12T10:30:00")],
        )
        self.assertEqual(
            ["retrieved_at_requires_timezone"], self.codes(validate_envelope(envelope, self.root))
        )

    def test_unparseable_timestamp_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence(relative, data, retrieved_at="12/09/2026 10:30")],
        )
        self.assertEqual(["invalid_retrieved_at"], self.codes(validate_envelope(envelope, self.root)))

    def test_malformed_digest_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()], [self.evidence(relative, data, content_sha256="not-a-sha256")]
        )
        self.assertEqual(["invalid_content_sha256"], self.codes(validate_envelope(envelope, self.root)))

    def test_wrong_length_digest_is_rejected(self):
        data = b"Metadata fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        for bad in ("a" * 63, "a" * 65, "g" * 64):
            envelope = self.envelope(
                [self.available_claim()], [self.evidence(relative, data, content_sha256=bad)]
            )
            self.assertEqual(["invalid_content_sha256"], self.codes(validate_envelope(envelope, self.root)), bad)


class PathSecurityTests(SnapshotTestCase):
    def test_nonexistent_snapshot_is_rejected(self):
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("missing.txt", b"unused", content_sha256=digest_of(b"unused"))],
        )
        self.assertEqual(["snapshot_missing"], self.codes(validate_envelope(envelope, self.root)))

    def test_embedded_nul_in_snapshot_path_is_a_finding(self):
        data = b"NUL path fixture.\n"
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("snap\x00shot.txt", data)],
        )
        result = validate_envelope(envelope, self.root)
        self.assertEqual(["snapshot_path_invalid"], self.codes(result))
        self.assertFalse(result.valid)

    def test_absolute_unix_snapshot_path_is_rejected(self):
        data = b"unused"
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("/etc/passwd", data)],
        )
        self.assertEqual(["snapshot_path_absolute"], self.codes(validate_envelope(envelope, self.root)))

    def test_absolute_windows_snapshot_path_is_rejected(self):
        data = b"unused"
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("C:\\Windows\\synthetic.txt", data)],
        )
        self.assertEqual(["snapshot_path_absolute"], self.codes(validate_envelope(envelope, self.root)))

    def test_parent_traversal_is_rejected(self):
        data = b"Escape fixture.\n"
        self.write_snapshot("nested/keep.txt", data)
        (self.root.parent / "escape.txt").write_bytes(data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("../escape.txt", data)],
        )
        result = validate_envelope(envelope, self.root)
        self.assertEqual(["snapshot_outside_root"], self.codes(result))

    def test_nested_traversal_is_rejected(self):
        data = b"Escape fixture.\n"
        self.write_snapshot("nested/keep.txt", data)
        (self.root.parent / "escape.txt").write_bytes(data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("nested/../../escape.txt", data)],
        )
        self.assertEqual(["snapshot_outside_root"], self.codes(validate_envelope(envelope, self.root)))

    def _symlinks_supported(self) -> bool:
        try:
            (self.root / "symlink-probe").symlink_to(self.root / "keep.txt")
        except (OSError, NotImplementedError):
            return False
        return True

    def test_symlink_escape_is_rejected(self):
        data = b"Escape fixture.\n"
        self.write_snapshot("keep.txt", data)
        outside = self.root.parent / "outside.txt"
        outside.write_bytes(data)
        if not self._symlinks_supported():
            self.skipTest("symlinks are not available on this account or platform")
        (self.root / "innocent.txt").symlink_to(outside)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence("innocent.txt", data)],
        )
        self.assertEqual(["snapshot_outside_root"], self.codes(validate_envelope(envelope, self.root)))

    def test_symlink_inside_root_is_accepted(self):
        data = b"Internal symlink fixture.\n"
        self.write_snapshot("nested/real.txt", data)
        if not self._symlinks_supported():
            self.skipTest("symlinks are not available on this account or platform")
        (self.root / "link.txt").symlink_to(self.root / "nested" / "real.txt")
        envelope = self.envelope(
            [self.available_claim()], [self.evidence("link.txt", data)]
        )
        self.assertTrue(validate_envelope(envelope, self.root).valid)

    def test_symlink_loop_is_a_finding(self):
        data = b"Loop fixture.\n"
        if not self._symlinks_supported():
            self.skipTest("symlinks are not available on this account or platform")
        (self.root / "loop-a").symlink_to(self.root / "loop-b")
        (self.root / "loop-b").symlink_to(self.root / "loop-a")
        envelope = self.envelope(
            [self.available_claim()], [self.evidence("loop-a", data)]
        )
        result = validate_envelope(envelope, self.root)
        self.assertEqual(["snapshot_outside_root"], self.codes(result))
        self.assertFalse(result.valid)

    def test_oversized_snapshot_is_rejected(self):
        data = b"0123456789"
        relative = self.write_snapshot("big.txt", data)
        envelope = self.envelope(
            [self.available_claim()], [self.evidence(relative, data)]
        )
        result = validate_envelope(envelope, self.root, max_file_size=4)
        self.assertEqual(["snapshot_too_large"], self.codes(result))
        # The same envelope passes with the default limit.
        self.assertTrue(validate_envelope(envelope, self.root).valid)

    def test_snapshot_at_exact_size_limit_is_accepted(self):
        data = b"1234"
        relative = self.write_snapshot("exact.txt", data)
        envelope = self.envelope(
            [self.available_claim()], [self.evidence(relative, data)]
        )
        self.assertTrue(validate_envelope(envelope, self.root, max_file_size=4).valid)
        self.assertEqual(
            ["snapshot_too_large"],
            self.codes(validate_envelope(envelope, self.root, max_file_size=3)),
        )

    def test_default_maximum_is_twenty_megabytes(self):
        self.assertEqual(20 * 1024 * 1024, DEFAULT_MAX_FILE_SIZE_BYTES)

    def test_digest_mismatch_is_rejected(self):
        data = b"Captured bytes fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope(
            [self.available_claim()],
            [self.evidence(relative, data, content_sha256=digest_of(b"different bytes"))],
        )
        self.assertEqual(["snapshot_hash_mismatch"], self.codes(validate_envelope(envelope, self.root)))

    def test_directory_snapshot_is_rejected(self):
        data = b"Directory fixture.\n"
        relative = self.write_snapshot("nested/source.txt", data)
        envelope = self.envelope(
            [self.available_claim()], [self.evidence("nested", data)]
        )
        self.assertEqual(["snapshot_not_regular_file"], self.codes(validate_envelope(envelope, self.root)))

    def test_only_cited_snapshots_are_read(self):
        data = b"Cited fixture.\n"
        relative = self.write_snapshot("cited.txt", data)
        self.write_snapshot("uncited.txt", b"Uncited fixture.\n")
        envelope = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        self.assertTrue(validate_envelope(envelope, self.root).valid)


class ReportContractTests(SnapshotTestCase):
    def test_findings_carry_exactly_the_six_contract_fields(self):
        envelope = self.envelope([self.available_claim([])], [])
        result = validate_envelope(envelope, self.root)
        self.assertEqual(
            {"line", "organisation_number", "claim_index", "evidence_id", "code", "message"},
            set(result.findings[0]),
        )
        self.assertEqual("123456789", result.findings[0]["organisation_number"])

    def test_findings_are_sorted_deterministically(self):
        envelope = self.envelope(
            [
                self.available_claim(["ev-b"]),
                self.available_claim([]),
            ],
            [self.evidence("x.txt", b"x", id="ev-a"), self.evidence("x.txt", b"x", id="ev-a")],
        )
        result = validate_envelope(envelope, self.root)
        # duplicate (claim None) < claim 0 < claim 1; codes alphabetical inside a group.
        self.assertEqual(
            ["duplicate_evidence_id", "missing_evidence_record", "available_claim_has_no_evidence"],
            self.codes(result),
        )
        self.assertEqual(
            [finding for finding in result.findings],
            sorted(result.findings, key=lambda f: (f["line"], f["claim_index"] if f["claim_index"] is not None else -1, f["evidence_id"] or "", f["code"])),
        )

    def test_report_json_contains_no_snapshot_contents_or_claim_values(self):
        data = b"Secret synthetic snapshot content marker.\n"
        relative = self.write_snapshot("source.txt", data)
        claim_value = "very-distinctive-claim-value-marker"
        envelope = self.envelope(
            [self.available_claim(value=claim_value)],
            [self.evidence(relative, data)],
        )
        report = validate_input(self._write_jsonl(envelope), self.root)
        self.assertTrue(report["valid"])
        rendered = json.dumps(report)
        self.assertNotIn(claim_value, rendered)
        self.assertNotIn("Secret synthetic snapshot content marker", rendered)

    def _write_jsonl(self, *envelopes) -> Path:
        path = Path(self._temp.name) / "input.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for envelope in envelopes:
                handle.write(json.dumps(envelope) + "\n")
        return path


class InputProcessingTests(SnapshotTestCase):
    def test_empty_input_is_reported_as_failed_run(self):
        path = Path(self._temp.name) / "empty.jsonl"
        path.write_bytes(b"")
        report = validate_input(path, self.root)
        self.assertFalse(report["valid"])
        self.assertEqual(0, report["envelopes_checked"])
        self.assertEqual(0, report["citations_checked"])
        self.assertEqual(
            [{"code": "empty_input", "line": 0}],
            [{"code": f["code"], "line": f["line"]} for f in report["findings"]],
        )
        self.assertIsNone(report["findings"][0]["organisation_number"])

    def test_whitespace_only_input_is_reported_as_failed_run(self):
        path = Path(self._temp.name) / "blank.jsonl"
        path.write_text("\n   \n", encoding="utf-8")
        report = validate_input(path, self.root)
        self.assertFalse(report["valid"])
        self.assertEqual("empty_input", report["findings"][0]["code"])

    def test_malformed_json_line_is_a_finding_not_a_crash(self):
        data = b"Good envelope fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        good = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        path = Path(self._temp.name) / "mixed.jsonl"
        path.write_text(
            "{not json\n" + json.dumps(good) + "\n",
            encoding="utf-8",
        )
        report = validate_input(path, self.root)
        self.assertFalse(report["valid"])
        self.assertEqual(1, report["envelopes_checked"])
        self.assertEqual(
            [(1, "malformed_json_line")],
            [(f["line"], f["code"]) for f in report["findings"]],
        )

    def test_blank_lines_keep_one_based_numbering(self):
        data = b"Numbering fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        good = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        path = Path(self._temp.name) / "numbered.jsonl"
        path.write_text(json.dumps(good) + "\n\n" + "{bad\n", encoding="utf-8")
        report = validate_input(path, self.root)
        malformed = [f for f in report["findings"] if f["code"] == "malformed_json_line"]
        self.assertEqual([3], [f["line"] for f in malformed])

    def test_report_has_exact_top_level_fields(self):
        path = Path(self._temp.name) / "shape.jsonl"
        path.write_bytes(b"")
        report = validate_input(path, self.root)
        self.assertEqual(
            {
                "validator",
                "valid",
                "envelopes_checked",
                "citations_checked",
                "factual_support_verified",
                "entity_binding_verified",
                "findings",
            },
            set(report),
        )
        self.assertEqual(VALIDATOR_ID, report["validator"])
        self.assertIs(False, report["factual_support_verified"])
        self.assertIs(False, report["entity_binding_verified"])

    def test_multi_envelope_counts_sum(self):
        data = b"Multi envelope fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        path = Path(self._temp.name) / "multi.jsonl"
        path.write_text(json.dumps(envelope) + "\n" + json.dumps(envelope) + "\n", encoding="utf-8")
        report = validate_input(path, self.root)
        self.assertEqual(2, report["envelopes_checked"])
        self.assertEqual(2, report["citations_checked"])


class LibraryApiTests(SnapshotTestCase):
    def test_library_function_accepts_envelope_root_and_max_size(self):
        data = b"Library API fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        result = validate_envelope(envelope, self.root, max_file_size=DEFAULT_MAX_FILE_SIZE_BYTES)
        self.assertTrue(result.valid)
        self.assertEqual([], result.findings)
        self.assertEqual(1, result.citations_checked)

    def test_library_rejects_non_dict_envelope(self):
        with self.assertRaises(TypeError):
            validate_envelope(["not", "a", "dict"], self.root)

    def test_max_file_size_must_be_a_positive_integer(self):
        data = b"Size type fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                validate_envelope(envelope, self.root, max_file_size=bad)
        for bad in (1.5, "20", None, True, False):
            with self.assertRaises(TypeError):
                validate_envelope(envelope, self.root, max_file_size=bad)
        path = Path(self._temp.name) / "size.jsonl"
        path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_input(path, self.root, max_file_size=0)
        with self.assertRaises(TypeError):
            validate_input(path, self.root, max_file_size=True)


class NoNetworkTests(SnapshotTestCase):
    def test_validation_makes_no_network_requests(self):
        def refuse(*args, **kwargs):
            raise AssertionError("the validator must not open network sockets")

        data = b"Offline fixture.\n"
        relative = self.write_snapshot("source.txt", data)
        envelope = self.envelope([self.available_claim()], [self.evidence(relative, data)])
        path = self._write_jsonl_for(envelope)
        with mock.patch.object(socket, "socket", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "socketpair", refuse):
            report = validate_input(path, self.root)
        self.assertTrue(report["valid"])

    def _write_jsonl_for(self, envelope) -> Path:
        path = Path(self._temp.name) / "offline.jsonl"
        path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
