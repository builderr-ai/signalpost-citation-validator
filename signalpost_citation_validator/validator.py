"""Core citation validation logic.

Byte-linkage only: the validator checks envelope structure, evidence metadata
and that cited snapshot files exist inside the snapshot root with bytes whose
SHA-256 digest matches ``content_sha256``. It never opens a network socket,
never reads uncited files and never embeds snapshot contents or claim values
in a finding.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

VALIDATOR_ID = "signalpost_public_citation_v1"
DEFAULT_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")

# Finding field order matches the public report contract.
Finding = dict[str, Any]


def finding_sort_key(finding: Finding) -> tuple[int, int, str, str]:
    """Deterministic finding order: line, claim index, evidence ID, code."""
    line = finding["line"]
    claim_index = finding["claim_index"]
    evidence_id = finding["evidence_id"]
    return (
        line,
        claim_index if isinstance(claim_index, int) else -1,
        evidence_id if isinstance(evidence_id, str) else "",
        finding["code"],
    )


@dataclass
class EnvelopeResult:
    """Outcome of validating a single parsed envelope."""

    findings: list[Finding] = field(default_factory=list)
    citations_checked: int = 0

    @property
    def valid(self) -> bool:
        return not self.findings


def _make_finding(
    line: int,
    organisation_number: str | None,
    claim_index: int | None,
    evidence_id: str | None,
    code: str,
    message: str,
) -> Finding:
    return {
        "line": line,
        "organisation_number": organisation_number,
        "claim_index": claim_index,
        "evidence_id": evidence_id,
        "code": code,
        "message": message,
    }


def _require_positive_int_max_file_size(max_file_size: Any) -> int:
    """Return ``max_file_size`` after checking it is a positive integer.

    ``bool`` is rejected even though it is an ``int`` subclass, so ``True``
    cannot silently become a 1-byte limit. Invalid values raise ``TypeError``
    or ``ValueError`` rather than producing undefined validation behaviour.
    """
    if isinstance(max_file_size, bool) or not isinstance(max_file_size, int):
        raise TypeError("max_file_size must be a positive integer")
    if max_file_size <= 0:
        raise ValueError("max_file_size must be a positive integer")
    return max_file_size


def _contains_unsafe_url_characters(value: str) -> bool:
    """Return True when ``value`` has characters a safe HTTP(S) URL cannot contain.

    ASCII control characters (including NUL, newline, tab, CR), DEL and any
    Unicode whitespace are rejected. Percent-encoded sequences such as ``%20``
    remain allowed because they are printable ASCII.
    """
    return any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in value)


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if _contains_unsafe_url_characters(value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if not parts.hostname:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    return True


def _retrieved_at_code(value: Any) -> str | None:
    """Return a finding code for a bad ``retrieved_at``, or None if valid."""
    if not isinstance(value, str):
        return "invalid_retrieved_at"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "invalid_retrieved_at"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "retrieved_at_requires_timezone"
    return None


def _is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _resolve_snapshot(snapshot_path: Any, root: Path) -> tuple[Path | None, str | None]:
    """Resolve a cited snapshot path inside the snapshot root.

    Returns ``(resolved_path, None)`` when the path is usable, or
    ``(None, finding_code)`` when it must be rejected. A valid symlink that
    stays inside the root is accepted; any symlink resolving outside is not.
    Embedded NUL bytes and other pathlib-invalid characters become a path
    finding instead of aborting the run.
    """
    if not isinstance(snapshot_path, str) or not snapshot_path.strip():
        return None, "snapshot_path_invalid"
    if "\x00" in snapshot_path:
        return None, "snapshot_path_invalid"

    try:
        posix = PurePosixPath(snapshot_path)
        windows = PureWindowsPath(snapshot_path)
        native = Path(snapshot_path)
    except (ValueError, OSError):
        return None, "snapshot_path_invalid"

    if (
        posix.is_absolute()
        or posix.root
        or windows.is_absolute()
        or windows.root
        or windows.drive
        or native.is_absolute()
    ):
        return None, "snapshot_path_absolute"

    if ".." in posix.parts or ".." in windows.parts:
        return None, "snapshot_outside_root"

    try:
        resolved_root = root.resolve()
        target = (root / native).resolve()
    except ValueError:
        return None, "snapshot_path_invalid"
    except OSError:
        return None, "snapshot_outside_root"
    if target == resolved_root or not target.is_relative_to(resolved_root):
        return None, "snapshot_outside_root"
    return target, None


def _validate_cited_evidence(
    evidence: Any,
    root: Path,
    max_file_size: int,
) -> list[tuple[str, str]]:
    """Validate one evidence record cited by a claim.

    Returns a list of ``(code, message)`` pairs, in a fixed field order so
    that repeated runs produce identical output.
    """
    problems: list[tuple[str, str]] = []

    if not _is_http_url(evidence.get("source_url")):
        problems.append(
            (
                "invalid_source_url",
                "source_url must be an http or https URL without embedded credentials",
            )
        )

    retrieved_at_code = _retrieved_at_code(evidence.get("retrieved_at"))
    if retrieved_at_code == "retrieved_at_requires_timezone":
        problems.append(
            (
                "retrieved_at_requires_timezone",
                "retrieved_at must be an ISO 8601 timestamp with a timezone",
            )
        )
    elif retrieved_at_code == "invalid_retrieved_at":
        problems.append(
            ("invalid_retrieved_at", "retrieved_at must be a valid ISO 8601 timestamp")
        )

    if not _is_sha256_hex(evidence.get("content_sha256")):
        problems.append(
            (
                "invalid_content_sha256",
                "content_sha256 must be exactly 64 hexadecimal characters",
            )
        )

    target, path_code = _resolve_snapshot(evidence.get("snapshot_path"), root)
    if path_code == "snapshot_path_invalid":
        problems.append(("snapshot_path_invalid", "snapshot_path must be a non-empty relative path"))
    elif path_code == "snapshot_path_absolute":
        problems.append(("snapshot_path_absolute", "snapshot_path must not be absolute"))
    elif path_code == "snapshot_outside_root":
        problems.append(("snapshot_outside_root", "snapshot_path must resolve inside the snapshot root"))

    if target is not None and path_code is None:
        if not target.exists():
            problems.append(("snapshot_missing", "snapshot_path does not resolve to an existing file"))
        elif not target.is_file():
            problems.append(("snapshot_not_regular_file", "snapshot_path must resolve to a regular file"))
        else:
            size = target.stat().st_size
            if size > max_file_size:
                problems.append(
                    ("snapshot_too_large", "snapshot file is larger than the configured maximum size")
                )
            else:
                recorded = evidence.get("content_sha256")
                if _is_sha256_hex(recorded):
                    try:
                        digest = hashlib.sha256(target.read_bytes()).hexdigest()
                    except OSError:
                        problems.append(("snapshot_unreadable", "snapshot file could not be read"))
                    else:
                        if digest != recorded.lower():
                            problems.append(
                                (
                                    "snapshot_hash_mismatch",
                                    "Captured bytes do not match content_sha256",
                                )
                            )
    return problems


def validate_envelope(
    envelope: dict[str, Any],
    snapshot_root: str | Path,
    *,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    line: int = 1,
) -> EnvelopeResult:
    """Validate one parsed result envelope against captured snapshot files.

    ``envelope`` must be a mapping as produced by ``json.loads`` on one JSONL
    line. ``snapshot_root`` is the directory holding the caller's captured
    source files. ``max_file_size`` bounds the size of each cited snapshot
    file and must be a positive integer; ``bool`` values and non-integers
    raise ``TypeError``, and zero or negative values raise ``ValueError``.
    ``line`` is the one-based JSONL line number used in findings.

    Only evidence records cited by claims are validated in depth, and only
    cited snapshot files are read.
    """
    max_file_size = _require_positive_int_max_file_size(max_file_size)
    if not isinstance(envelope, dict):
        raise TypeError("envelope must be a parsed JSON object (dict)")

    organisation_number = envelope.get("organisation_number")
    if not isinstance(organisation_number, str):
        organisation_number = None

    result = EnvelopeResult()

    def add(claim_index: int | None, evidence_id: str | None, code: str, message: str) -> None:
        result.findings.append(
            _make_finding(line, organisation_number, claim_index, evidence_id, code, message)
        )

    evidence_items = envelope.get("evidence")
    if evidence_items is None:
        evidence_items = []
    if not isinstance(evidence_items, list):
        add(None, None, "invalid_evidence", "evidence must be a list")
        evidence_items = []

    # First occurrence wins so duplicate declarations cannot change which
    # record a citation resolves to.
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for item in evidence_items:
        if not isinstance(item, dict):
            add(None, None, "invalid_evidence_record", "evidence entries must be JSON objects")
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            add(None, None, "invalid_evidence_id", "evidence entries must have a non-empty string id")
            continue
        if identifier in evidence_by_id:
            add(None, identifier, "duplicate_evidence_id", "Evidence ID is declared more than once in the envelope")
        else:
            evidence_by_id[identifier] = item

    claims = envelope.get("claims")
    if claims is None:
        claims = []
    if not isinstance(claims, list):
        add(None, None, "invalid_claims", "claims must be a list")
        claims = []

    root = Path(snapshot_root)
    cited_ids: set[str] = set()
    validated_ids: set[str] = set()

    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            add(claim_index, None, "invalid_claim", "claims entries must be JSON objects")
            continue

        evidence_ids = claim.get("evidence_ids")
        if evidence_ids is None:
            evidence_ids = []
        if not isinstance(evidence_ids, list):
            add(claim_index, None, "invalid_evidence_ids", "evidence_ids must be a list of evidence ID strings")
            evidence_ids = []
        string_ids = [item for item in evidence_ids if isinstance(item, str) and item]
        if len(string_ids) != len(evidence_ids):
            add(claim_index, None, "invalid_evidence_ids", "evidence_ids must be a list of evidence ID strings")

        if claim.get("availability") == "available" and not string_ids:
            add(
                claim_index,
                None,
                "available_claim_has_no_evidence",
                "Available claim must cite at least one evidence ID",
            )

        cited_ids.update(string_ids)
        for identifier in dict.fromkeys(string_ids):
            evidence_record = evidence_by_id.get(identifier)
            if evidence_record is None:
                add(
                    claim_index,
                    identifier,
                    "missing_evidence_record",
                    "Cited evidence ID does not exist in the envelope",
                )
                continue
            if identifier in validated_ids:
                continue
            validated_ids.add(identifier)
            for code, message in _validate_cited_evidence(evidence_record, root, max_file_size):
                # Evidence metadata findings attach to the first claim that
                # cites the record, mirroring the acceptance contract.
                add(claim_index, identifier, code, message)

    result.citations_checked = len(cited_ids)
    result.findings.sort(key=finding_sort_key)
    return result


def validate_input(
    input_path: str | Path,
    snapshot_root: str | Path,
    *,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> dict[str, Any]:
    """Validate a JSONL file of result envelopes and build the report.

    Every non-empty line is processed independently with its one-based line
    number preserved; a malformed JSON line becomes a finding instead of
    aborting the run. An input with no envelopes is reported as a failed run
    through the ``empty_input`` finding, never as success.

    ``max_file_size`` must be a positive integer; see ``validate_envelope``.
    """
    max_file_size = _require_positive_int_max_file_size(max_file_size)
    findings: list[Finding] = []
    envelopes_checked = 0
    citations_checked = 0
    saw_envelope_or_line = False

    with open(input_path, "r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            saw_envelope_or_line = True
            try:
                envelope = json.loads(raw_line)
            except json.JSONDecodeError:
                findings.append(
                    _make_finding(
                        line_number, None, None, None, "malformed_json_line", "Line is not valid JSON"
                    )
                )
                continue
            if not isinstance(envelope, dict):
                findings.append(
                    _make_finding(
                        line_number, None, None, None, "invalid_envelope", "Envelope must be a JSON object"
                    )
                )
                continue
            result = validate_envelope(
                envelope, snapshot_root, max_file_size=max_file_size, line=line_number
            )
            findings.extend(result.findings)
            envelopes_checked += 1
            citations_checked += result.citations_checked

    if not saw_envelope_or_line:
        findings.append(
            _make_finding(0, None, None, None, "empty_input", "Input contains no result envelopes")
        )

    findings.sort(key=finding_sort_key)
    return {
        "validator": VALIDATOR_ID,
        "valid": not findings,
        "envelopes_checked": envelopes_checked,
        "citations_checked": citations_checked,
        "factual_support_verified": False,
        "entity_binding_verified": False,
        "findings": findings,
    }
