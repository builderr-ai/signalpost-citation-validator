"""Focused CLI tests for the citation validator.

Runs the CLI both in-process (exit codes, argument handling) and as a real
``python -m signalpost_citation_validator`` subprocess (module entry point,
deterministic repeated output). No network access is possible because the
tests never construct one and the validator only touches local files.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from signalpost_citation_validator.cli import main

ROOT = Path(__file__).resolve().parents[1]


def digest_of(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


class CliHarness(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name)
        self.root = self.base / "snapshots-root"
        self.root.mkdir()

    def write_valid_input(self) -> tuple[Path, Path]:
        data = b"CLI fixture snapshot bytes.\n"
        snapshot = self.root / "source.txt"
        snapshot.write_bytes(data)
        envelope = {
            "organisation_number": "123456789",
            "claims": [
                {
                    "field": "synthetic_field",
                    "value": "synthetic-value",
                    "availability": "available",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "evidence": [
                {
                    "id": "ev-1",
                    "source_url": "https://example.org/source",
                    "retrieved_at": "2026-09-12T10:30:00Z",
                    "content_sha256": digest_of(data),
                    "snapshot_path": "source.txt",
                }
            ],
        }
        input_path = self.base / "input.jsonl"
        input_path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        return input_path, snapshot

    def write_invalid_input(self) -> Path:
        input_path = self.base / "invalid.jsonl"
        envelope = {
            "organisation_number": "123456789",
            "claims": [
                {
                    "field": "synthetic_field",
                    "value": "synthetic-value",
                    "availability": "available",
                    "evidence_ids": [],
                }
            ],
            "evidence": [],
        }
        input_path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        return input_path

    def run_cli(self, *args):
        return main(list(args))


class ExitCodeTests(CliHarness):
    def test_valid_input_exits_zero_and_writes_report(self):
        input_path, _ = self.write_valid_input()
        output_path = self.base / "report.json"
        self.assertEqual(0, self.run_cli("--input", str(input_path), "--snapshot-root", str(self.root), "--output", str(output_path)))
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])

    def test_findings_exit_nonzero_but_report_is_written(self):
        input_path = self.write_invalid_input()
        output_path = self.base / "report.json"
        status = self.run_cli("--input", str(input_path), "--snapshot-root", str(self.root), "--output", str(output_path))
        self.assertEqual(1, status)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertFalse(report["valid"])
        self.assertEqual("available_claim_has_no_evidence", report["findings"][0]["code"])

    def test_missing_input_file_exits_two_without_report(self):
        output_path = self.base / "report.json"
        status = self.run_cli(
            "--input", str(self.base / "absent.jsonl"),
            "--snapshot-root", str(self.root),
            "--output", str(output_path),
        )
        self.assertEqual(2, status)
        self.assertFalse(output_path.exists())

    def test_missing_required_arguments_are_rejected(self):
        with self.assertRaises(SystemExit) as context:
            self.run_cli("--input", "x.jsonl")
        self.assertEqual(2, context.exception.code)

    def test_embedded_nul_snapshot_path_writes_report(self):
        input_path = self.base / "nul.jsonl"
        envelope = {
            "organisation_number": "123456789",
            "claims": [
                {
                    "field": "synthetic_field",
                    "value": "synthetic-value",
                    "availability": "available",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "evidence": [
                {
                    "id": "ev-1",
                    "source_url": "https://example.org/source",
                    "retrieved_at": "2026-09-12T10:30:00Z",
                    "content_sha256": "a" * 64,
                    "snapshot_path": "snap\x00shot.txt",
                }
            ],
        }
        input_path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        output_path = self.base / "report.json"
        status = self.run_cli(
            "--input",
            str(input_path),
            "--snapshot-root",
            str(self.root),
            "--output",
            str(output_path),
        )
        self.assertEqual(1, status)
        self.assertTrue(output_path.is_file())
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertFalse(report["valid"])
        self.assertIn("snapshot_path_invalid", [finding["code"] for finding in report["findings"]])

    def test_symlink_loop_snapshot_path_writes_report(self):
        try:
            probe = self.root / "symlink-probe"
            probe.symlink_to(self.root / "keep.txt")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available on this account or platform")
        (self.root / "loop-a").symlink_to(self.root / "loop-b")
        (self.root / "loop-b").symlink_to(self.root / "loop-a")
        input_path = self.base / "loop.jsonl"
        envelope = {
            "organisation_number": "123456789",
            "claims": [
                {
                    "field": "synthetic_field",
                    "value": "synthetic-value",
                    "availability": "available",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "evidence": [
                {
                    "id": "ev-1",
                    "source_url": "https://example.org/source",
                    "retrieved_at": "2026-09-12T10:30:00Z",
                    "content_sha256": "a" * 64,
                    "snapshot_path": "loop-a",
                }
            ],
        }
        input_path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
        output_path = self.base / "report.json"
        status = self.run_cli(
            "--input",
            str(input_path),
            "--snapshot-root",
            str(self.root),
            "--output",
            str(output_path),
        )
        self.assertEqual(1, status)
        self.assertTrue(output_path.is_file())
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertFalse(report["valid"])
        self.assertIn("snapshot_outside_root", [finding["code"] for finding in report["findings"]])


class ModuleInvocationTests(CliHarness):
    def run_module(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "signalpost_citation_validator", *args],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_python_dash_m_invocation_writes_deterministic_report(self):
        input_path, _ = self.write_valid_input()
        first = self.base / "first.json"
        second = self.base / "second.json"
        for output_path in (first, second):
            result = self.run_module(
                "--input", str(input_path),
                "--snapshot-root", str(self.root),
                "--output", str(output_path),
            )
            self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        report = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual("signalpost_public_citation_v1", report["validator"])

    def test_python_dash_m_reports_findings_with_failure_status(self):
        input_path = self.write_invalid_input()
        output_path = self.base / "report.json"
        result = self.run_module(
            "--input", str(input_path),
            "--snapshot-root", str(self.root),
            "--output", str(output_path),
        )
        self.assertEqual(1, result.returncode)
        self.assertTrue(output_path.is_file())


if __name__ == "__main__":
    unittest.main()
