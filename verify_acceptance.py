#!/usr/bin/env python3
"""Black-box verifier for the public Signalpost citation fixture pack.

This runner compares a candidate CLI's public report with declared outcomes. It
does not implement citation validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = ROOT / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
VALIDATOR_ID = "signalpost_public_citation_v1"


class AcceptanceFailure(Exception):
    pass


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AcceptanceFailure("manifest must contain at least one case")

    identifiers = [case.get("id") for case in cases]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise AcceptanceFailure("every case must have a non-empty string id")
    if len(identifiers) != len(set(identifiers)):
        raise AcceptanceFailure("case ids must be unique")
    if identifiers != manifest.get("required_cases"):
        raise AcceptanceFailure("cases must exactly match required_cases in declared order")

    for relative, expected_digest in manifest.get("snapshot_sha256", {}).items():
        snapshot = FIXTURE_ROOT / relative
        actual_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise AcceptanceFailure(f"fixture snapshot digest changed: {relative}")
    return manifest


def finding_sort_key(finding: dict[str, Any]) -> tuple[int, int, str, str]:
    line = finding.get("line")
    claim_index = finding.get("claim_index")
    return (
        line if isinstance(line, int) else -1,
        claim_index if isinstance(claim_index, int) else -1,
        finding.get("evidence_id") if isinstance(finding.get("evidence_id"), str) else "",
        finding.get("code") if isinstance(finding.get("code"), str) else "",
    )


def check_report(case: dict[str, Any], report: Any) -> None:
    case_id = case["id"]
    expected = case["expected"]
    if not isinstance(report, dict):
        raise AcceptanceFailure(f"{case_id}: output must be a JSON object")

    exact_fields = {
        "validator": VALIDATOR_ID,
        "valid": expected["valid"],
        "envelopes_checked": expected["envelopes_checked"],
        "citations_checked": expected["citations_checked"],
        "factual_support_verified": False,
        "entity_binding_verified": False,
    }
    for field, value in exact_fields.items():
        if report.get(field) != value or type(report.get(field)) is not type(value):
            raise AcceptanceFailure(
                f"{case_id}: {field} must be {value!r}, got {report.get(field)!r}"
            )

    findings = report.get("findings")
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise AcceptanceFailure(f"{case_id}: findings must be a list of objects")
    if findings != sorted(findings, key=finding_sort_key):
        raise AcceptanceFailure(f"{case_id}: findings are not in deterministic contract order")
    codes = [finding.get("code") for finding in findings]
    if codes != expected["finding_codes"]:
        raise AcceptanceFailure(
            f"{case_id}: finding codes must be {expected['finding_codes']!r}, got {codes!r}"
        )


def run_candidate(command: list[str], timeout_seconds: float) -> int:
    manifest = load_manifest()
    cases = manifest["cases"]
    passed = 0

    with tempfile.TemporaryDirectory(prefix="signalpost-citation-acceptance-") as temporary:
        temp_root = Path(temporary)
        for case in cases:
            case_id = case["id"]
            input_path = temp_root / f"{case_id}.jsonl"
            envelope = case["envelope"]
            if envelope is None:
                input_path.write_bytes(b"")
            else:
                line = json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n"
                input_path.write_text(line, encoding="utf-8")

            raw_outputs: list[bytes] = []
            parsed_outputs: list[Any] = []
            for run_number in (1, 2):
                output_path = temp_root / f"{case_id}-{run_number}.json"
                invocation = command + [
                    "--input",
                    str(input_path),
                    "--snapshot-root",
                    str(FIXTURE_ROOT),
                    "--output",
                    str(output_path),
                ]
                try:
                    result = subprocess.run(
                        invocation,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=timeout_seconds,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    raise AcceptanceFailure(f"{case_id}: candidate timed out") from error
                except OSError as error:
                    raise AcceptanceFailure(f"could not start candidate: {error}") from error

                if not output_path.is_file():
                    stderr = result.stderr.decode("utf-8", errors="replace")[:400].strip()
                    detail = f"; stderr: {stderr}" if stderr else ""
                    raise AcceptanceFailure(
                        f"{case_id}: candidate did not create --output (exit {result.returncode}){detail}"
                    )
                raw = output_path.read_bytes()
                try:
                    parsed = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise AcceptanceFailure(f"{case_id}: --output is not valid UTF-8 JSON") from error
                raw_outputs.append(raw.rstrip())
                parsed_outputs.append(parsed)

            if raw_outputs[0] != raw_outputs[1]:
                raise AcceptanceFailure(f"{case_id}: repeated runs produced different JSON bytes")
            check_report(case, parsed_outputs[0])
            passed += 1
            print(f"PASS {case_id}")

    if passed == 0:
        raise AcceptanceFailure("zero fixture cases were exercised")
    print(f"PASS {passed} fixture cases; each candidate invocation was repeated")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the public fixture pack against a candidate citation-validator CLI."
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds per invocation")
    parser.add_argument(
        "candidate",
        nargs=argparse.REMAINDER,
        help="candidate command after --, for example: -- python -m citation_validator",
    )
    args = parser.parse_args()
    if args.candidate[:1] == ["--"]:
        args.candidate = args.candidate[1:]
    if not args.candidate:
        parser.error("provide a candidate command after --")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return args


def main() -> int:
    args = parse_args()
    try:
        return run_candidate(args.candidate, args.timeout)
    except AcceptanceFailure as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
