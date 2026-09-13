# Validate that Signalpost claims point to the source files we captured

Signalpost agents return company facts with links to supporting evidence. We need a small offline validator that catches broken evidence references before a result reaches evaluation.

Challenge context: [build an agent that finds reliable public company information](https://builderr.ai/challenges/signalpost?utm_source=github&utm_medium=open_contribution&utm_campaign=signalpost_citation_validator).

Implement a Python 3.11 citation validator for Signalpost result envelopes. It should check structure and captured bytes only. It must not crawl the web, decide whether a claim is true, decide whether a source belongs to the right company, or calculate a competition score.

### Input

The validator receives:

1. a JSONL file with one result envelope per line; and
2. a directory containing source snapshots captured by the caller.

The claim and evidence fields match the current public Signalpost output contract. This validator bundle adds `snapshot_path`, a path to the caller's captured source file:

```json
{
  "organisation_number": "123456789",
  "claims": [
    {
      "field": "official_website",
      "value": "https://example.org/",
      "availability": "available",
      "evidence_ids": ["ev-home"]
    }
  ],
  "evidence": [
    {
      "id": "ev-home",
      "source_url": "https://example.org/company",
      "retrieved_at": "2026-09-12T10:30:00Z",
      "content_sha256": "0174da810c0f6e39268e8698002331b3fd93e59487b58a393e344642c69a9312",
      "snapshot_path": "snapshots/company-homepage.txt"
    }
  ]
}
```

Treat `0`, `false` and an empty list as real values. Do not turn them into missing values. An `available` claim must cite at least one evidence ID. Claims in other availability states may have no evidence reference.

### Checks

For each envelope:

- evidence IDs are unique;
- every `available` claim has at least one `evidence_ids` entry;
- every cited evidence ID exists;
- each cited `source_url` is an `http` or `https` URL without embedded credentials;
- each cited `retrieved_at` is an ISO 8601 timestamp with a timezone;
- each cited `content_sha256` is 64 hexadecimal characters;
- each cited `snapshot_path` is relative, resolves inside the supplied snapshot directory, is a regular file and is no larger than 20 MB by default; and
- the SHA-256 digest of the captured bytes matches `content_sha256`.

Reject absolute paths, `..` escapes and symlink escapes. Read only cited snapshot files. The validator must perform no network requests.

### Output

Write one deterministic JSON report. The report must contain:

```json
{
  "validator": "signalpost_public_citation_v1",
  "valid": false,
  "envelopes_checked": 1,
  "citations_checked": 1,
  "factual_support_verified": false,
  "entity_binding_verified": false,
  "findings": [
    {
      "line": 1,
      "organisation_number": "123456789",
      "claim_index": 0,
      "evidence_id": "ev-home",
      "code": "snapshot_hash_mismatch",
      "message": "Captured bytes do not match content_sha256"
    }
  ]
}
```

Sort findings by input line, claim index, evidence ID and code so repeated runs produce byte-for-byte equivalent JSON apart from optional trailing whitespace. Do not copy snapshot contents or claim values into the report.

`citations_checked` counts distinct evidence IDs cited by claims within each envelope, then sums those per-envelope counts. Reusing one evidence record for two claims in the same envelope counts once.

The two `*_verified` fields must always be `false`. Passing this validator proves that a claim points to the captured bytes identified by its digest. It does not prove the factual claim or company identity.

### Fixtures and tests

Use the synthetic fixture pack in this repository. It contains no live company data, private submission, hidden competition test, credential or evaluator answer. Its expected finding codes are deliberately public acceptance examples. The cases cover:

- a valid cited claim;
- valid `0`, `false` and `[]` values, plus a `not_available` claim;
- an available claim with no reference;
- a missing evidence record;
- duplicate evidence IDs;
- a non-web URL, timezone-free timestamp and malformed digest;
- a path escape; and
- a captured file whose digest does not match.

Add focused tests for the function and CLI. The test command must run offline on Python 3.11 and must fail if it discovers zero tests or zero fixture cases.

### Definition of done

- A library function accepts an envelope, a snapshot root and an optional maximum file size.
- A CLI accepts `--input`, `--snapshot-root` and `--output`.
- All supplied fixture cases pass with their exact expected finding codes.
- Re-running the same input produces deterministic finding order.
- A test proves that absolute paths, `..` paths and a symlink resolving outside the snapshot root are rejected.
- A test proves that `0`, `false` and `[]` values are preserved and are not treated as missing.
- A test proves that an empty input is not reported as a successful validation run.
- Tests make no network requests and use only the Python standard library unless the repository already has an approved validation dependency.
- The README explains the validator's limits: byte linkage only, with no factual-support, company-identity, collection-rights or competition-score claim.

### Ownership, licence and reward

This repository uses the MIT License. Contributors retain copyright and license submitted contributions under the same terms. No copyright assignment or contributor licence agreement is required. Do not copy code from participant submissions.

There is no cash bounty for this pilot. A merged contribution does not affect Signalpost judging, prizes or leaderboard position. If Builderr later adds a bounty, that requires a separate written budget and updated issue terms before work begins.

If you want to work on this, comment with the part you plan to implement before opening a pull request.
