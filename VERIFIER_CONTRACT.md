# Acceptance verifier contract

`verify_acceptance.py` is a black-box runner. It must not be copied into the
validator package as validation logic.

Invoke it with the candidate CLI after `--`:

```sh
python3 verify_acceptance.py -- python3 -m signalpost_citation_validator
```

For every manifest case, the runner creates a JSONL input, appends the required
`--input`, `--snapshot-root`, and `--output` arguments, and runs the command
twice. It accepts either success or validation-failure process status when a
valid output report is written, because the prepared issue does not prescribe
CLI exit codes.

Acceptance requires:

- all nine declared cases run; zero cases is a verifier failure;
- output is UTF-8 JSON and contains the required public report fields;
- `validator` is `signalpost_public_citation_v1`;
- validity, envelope count, distinct per-envelope citation count, and ordered
  finding codes exactly match the manifest;
- `factual_support_verified` and `entity_binding_verified` are Boolean `false`;
- findings are sorted by line, claim index, evidence ID, and code; and
- the two runs produce identical JSON bytes after trailing whitespace is removed.

The runner checks fixture-file digests only to detect accidental changes to the
pack. It does not inspect source semantics, decide factual support, bind an
organisation to a source, crawl the web, or calculate a score. Run it in an
offline test environment to enforce the issue's no-network requirement.

The public issue also asks implementation-owned tests to reject absolute paths
and symlink escapes, enforce the size limit, and exercise the library function.
Those tests are intentionally outside this portable black-box fixture pack; the
pack's `path_escape` case covers a `..` traversal.
