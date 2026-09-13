# Signalpost citation validator

An offline tool project that helps builders catch broken Signalpost evidence references before submission.

The first contribution is a citation validator. It checks whether a claim points to a captured source file and whether the file matches its recorded SHA-256 digest. It does **not** decide whether the claim is true, whether the source belongs to the correct company, whether collecting the source was permitted, or how a competition entry should score.

This repository is being prepared locally. It has not been published on GitHub yet.

## Why this is public

The checks in this repository are safe to share with every builder. They use synthetic fixtures and contain no participant submission, private company record, credential, hidden evaluation case or competition answer.

Public acceptance tests help contributors understand exactly what a small tool must do. Passing them does not reveal or replace Builderr's independent assessment.

## First contribution

Read [the citation-validator issue](docs/citation-validator-issue.md). The task is deliberately narrow: Python 3.11, offline, deterministic output and standard-library-only unless a dependency is approved first.

The supplied fixture pack lives in `fixtures/`. Run its black-box verifier like this after implementing the CLI:

```sh
python3 verify_acceptance.py -- python3 -m signalpost_citation_validator
```

A contributor will add the validator implementation and focused tests in a pull request.

## Licence

Code and documentation in this repository are available under the [MIT License](LICENSE). Contributors retain copyright in their work and license submitted contributions under the same terms. No copyright assignment or CLA is required.

Contributing does not affect Signalpost judging, prizes or leaderboard position. There is no cash bounty for the first pilot.
