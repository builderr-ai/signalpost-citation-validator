"""Command-line interface for the Signalpost citation validator.

Exit codes:

- ``0``: a report was written and the input validated without findings;
- ``1``: a report was written but validation produced findings;
- ``2``: the validator could not run (usage error or unreadable input), so no
  report is produced.

The acceptance verifier accepts either success or validation-failure status
as long as a valid report file is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .validator import DEFAULT_MAX_FILE_SIZE_BYTES, validate_input


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signalpost_citation_validator",
        description=(
            "Offline byte-linkage validator for Signalpost result envelopes. "
            "Checks that claims point to captured snapshot files whose SHA-256 "
            "digests match the recorded content_sha256. Makes no network requests."
        ),
    )
    parser.add_argument("--input", required=True, help="JSONL file with one result envelope per line")
    parser.add_argument("--snapshot-root", required=True, help="directory containing captured source files")
    parser.add_argument("--output", required=True, help="path of the JSON report to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: input file does not exist: {input_path}", file=sys.stderr)
        return 2

    try:
        report = validate_input(input_path, args.snapshot_root)
    except OSError as error:
        print(f"error: could not validate input: {error}", file=sys.stderr)
        return 2

    output_path = Path(args.output)
    try:
        if output_path.parent and not output_path.parent.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as error:
        print(f"error: could not write report: {error}", file=sys.stderr)
        return 2

    return 0 if report["valid"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
