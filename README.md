# Signalpost citation validator

An offline tool project that helps builders catch broken evidence references before submitting to the [Signalpost challenge](https://builderr.ai/challenges/signalpost?utm_source=github&utm_medium=open_contribution&utm_campaign=signalpost_citation_validator).

The first contribution is a citation validator. It checks whether a claim points to a captured source file and whether the file matches its recorded SHA-256 digest. It does **not** decide whether the claim is true, whether the source belongs to the correct company, whether collecting the source was permitted, or how a competition entry should score.

This is a small public contribution project from [Builderr](https://builderr.ai/?utm_source=github&utm_medium=open_contribution&utm_campaign=signalpost_citation_validator&utm_content=readme_about), where companies pay for verified outcomes and builders compete with working solutions.

## Why this is public

The checks in this repository are safe to share with every builder. They use synthetic fixtures and contain no participant submission, private company record, credential, hidden evaluation case or competition answer.

Public acceptance tests help contributors understand exactly what a small tool must do. Passing them does not reveal or replace Builderr's independent assessment.

## First contribution

Read [the citation-validator issue](docs/citation-validator-issue.md). The task is deliberately narrow: Python 3.11, offline, deterministic output and standard-library-only unless a dependency is approved first.

The supplied fixture pack lives in `fixtures/`. Run its black-box verifier like this after implementing the CLI:

```sh
python3 verify_acceptance.py -- python3 -m signalpost_citation_validator
```

## Using the validator

The validator checks byte linkage only. Passing means that every `available` claim points to a captured source file identified by valid evidence metadata whose bytes match the recorded SHA-256 digest. It does **not** prove that a claim is factually true, that a source belongs to the stated company, that collecting the source was permitted, or how a competition entry should score. The report fields `factual_support_verified` and `entity_binding_verified` are always `false`.

### Library

```python
from signalpost_citation_validator import validate_envelope, validate_input

# One parsed envelope (as produced by json.loads on a JSONL line).
result = validate_envelope(envelope, "path/to/snapshot-root")

# Or a whole JSONL file, returning the full report dict.
report = validate_input("results.jsonl", "path/to/snapshot-root")
```

`validate_envelope` accepts one parsed envelope, the snapshot root and an optional `max_file_size` keyword (default 20 MB per cited file). It returns the findings plus the number of distinct evidence IDs cited by the envelope's claims. `validate_input` reads a JSONL file line by line and returns the complete report.

### CLI

```sh
python3 -m signalpost_citation_validator --input INPUT --snapshot-root ROOT --output OUTPUT
```

Exit codes: `0` when a report was written and validation found nothing, `1` when a report was written but findings exist, and `2` when the validator could not run (usage error or unreadable input), in which case no report is produced. The acceptance verifier accepts either success or validation-failure status as long as a valid report file is written.

### Behaviour and limits

- **Offline only.** The validator makes no network requests. It never crawls `source_url`; the URL is only checked for syntax (must be `http` or `https` with no embedded credentials).
- **Snapshot root required.** `snapshot_path` must be a relative path that resolves inside the supplied snapshot root and to a regular file. Absolute paths (POSIX or Windows style), `..` components and symlinks that resolve outside the root are rejected. Resolution always checks the final resolved path, never a string prefix. A symlink that stays inside the root is accepted.
- **Size limit.** A cited snapshot file larger than the maximum (20 MB by default, configurable with `max_file_size`) is rejected.
- **Only cited files are read.** The SHA-256 digest of each cited snapshot's bytes is compared with `content_sha256`. Uncited files are never opened.
- **Deterministic.** Findings are sorted by input line, claim index, evidence ID and code, and never contain snapshot contents or claim values. Repeating the same run produces byte-identical JSON apart from trailing whitespace.
- **Empty input fails.** A JSONL file with no envelopes is reported as a failed run (`empty_input`, `valid: false`), never as success. A malformed JSON line becomes a finding and does not abort the run.
- **`0`, `false` and `[]` are real values.** They are never treated as missing, and an `available` claim must still cite at least one evidence ID.

A longer explanation of the task is in [the citation-validator issue](docs/citation-validator-issue.md).

## Licence

Code and documentation in this repository are available under the [MIT License](LICENSE). Contributors retain copyright in their work and license submitted contributions under the same terms. No copyright assignment or CLA is required.

Contributing does not affect Signalpost judging, prizes or leaderboard position. There is no cash bounty for the first pilot.
