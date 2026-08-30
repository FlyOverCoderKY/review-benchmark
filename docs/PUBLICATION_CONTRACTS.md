# Official release and result contracts

These contracts are the public authority boundary. They are intentionally exact:
unknown fields, missing bindings, incomplete inventories, and ambiguous
supersession fail closed.

## Official releases

`review-benchmark/release/2` requires `status: official`, a lowercase 40-character
`public_benchmark_revision`, a sorted task list, and a sorted artifact inventory.
Every regular file below the release root except `MANIFEST.json` appears exactly
once with its byte size and SHA-256 digest. Validation rejects omitted or extra
files, traversal, non-normalized paths, case collisions, symlinks, junctions, and
other reparse points before task content is loaded.

Historical `release/1` calibration fixtures retain their published permissive
loader semantics, including extension fields and historical statuses. The
authoritative runner boundary explicitly requires `release/2`; a legacy release
cannot become an official run by changing a status field.

## Run adjudication overlays

`review-benchmark/run-adjudications/1` is a neutral private interchange contract.
It binds the run manifest, private score, configuration, release manifest and Git
revision, scorer Git revision and version, and the exact set of pending findings.
Each finding binding includes its task and attempt identity, normalized attempt
digest, finding index, and canonical finding digest.

Exactly two opaque reviewers independently provide a reason for each verdict.
Only unanimous `valid_extra` and `false_positive` decisions can clear publication.
`oracle_gap`, `insufficient_evidence`, and reviewer disagreement remain explicit
publication blockers. The pending-set and document digests use UTF-8 canonical
JSON: sorted keys, no insignificant whitespace, and no trailing newline.

## Public results

`review-benchmark/public-result/2` is the complete public-safe record. Its nested
subject, release, provenance, quality, and operations objects have exact fields.
It binds runner, scorer, public benchmark, selected release, product, configuration,
and release-manifest identities. Quality reports bug/risk/nit recall and detection
frequency across attempts. Latency and cost stay separate; unknown values are
`null`, never guessed as zero.

`subject.provider` is the configured route slug; it need not equal the provider
identity returned by the API. Official results require both values, disabled
fallbacks, and `operations.providers` exactly equal to the one-element list
containing `expected_reported_provider`.

`provenance.evaluation_config_sha256` is the canonical SHA-256 fingerprint of:

```json
{
  "schema": "review-benchmark/evaluation-config-fingerprint/1",
  "track": "<track>",
  "subject": "<exact subject object>",
  "release": "<exact release object with integral counts normalized to integers>",
  "evaluation_provenance": {
    "scorer_git_sha": "...",
    "public_benchmark_git_sha": "...",
    "release_git_sha": "...",
    "product_git_sha": "...",
    "release_manifest_sha256": "...",
    "scorer_version": "...",
    "provider_policy": "..."
  }
}
```

Here the quoted subject/release placeholders mean their exact documented nested
objects. The digest uses the same UTF-8, sorted-key, compact canonical JSON form
as adjudication bindings. It deliberately excludes `record_id`, `run_id`,
publication status, runner revision, raw `config_sha256`, quality, and operations.
A reproduction retains this stable digest and the release/product/scorer identity,
but has a distinct run ID and raw run-configuration digest.

The published `public-result/1` schema remains frozen at
`schemas/public-result.schema.json` for historical consumers. New authority
records use the separately identified `schemas/public-result-v2.schema.json`.

For official and reproduced records, every task-attempt cell must be scored, all
telemetry and costs must be present, and pending findings, failures, skipped
attempts, and cost-guard termination must all be absent.

Validate a candidate record with:

```bash
python -m review_benchmark validate-result path/to/record.json
```

## Append-only result registry

`results/registry.json` uses `review-benchmark/result-registry/1`. Entries are
sorted by `record_id` and contain exactly `record_id`, `path`, exact-byte
`sha256`, nullable `supersedes`, and nullable `reproduces`. A record path is
always `records/<record-id>.json`. The immutable publication `record_id` is
independent of `run_id`, so consumers route record history by `record_id`.

The digest is SHA-256 of the exact committed record-file bytes (the Git blob
payload), not a language-specific reserialization of parsed JSON. This makes
integers versus floats, Unicode escaping, whitespace, and line endings explicit
immutable bytes and lets Python and JavaScript consumers recompute the same value
without agreeing on a number formatter. `.gitattributes` marks `results/**`
non-text so Git never rewrites those bytes. The records directory must exactly
match the registry. Supersession is a linear, acyclic history between the same
track and subject; the earlier record remains immutable and present.

CI validates the current registry and compares it with the pull request's base Git
revision. Existing entries and record content cannot be modified or deleted.
`supersedes` is reserved for an immutable `superseded`, `withdrawn`, or
`disputed` disposition of the exact same run and evaluation identity.
`reproduces` relates a distinct run that repeats the same evaluation identity;
it is not a correction or disposition.

```bash
python -m review_benchmark validate-result-registry results/registry.json
python -m review_benchmark validate-result-registry results/registry.json \
  --base-ref <base-commit-sha>
```
