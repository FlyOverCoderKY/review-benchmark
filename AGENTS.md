# Working in review-benchmark

This repository is the public benchmark authority for automated code review.

## Hard rules

- Everything committed here is public-safe. Never add private task text, hidden
  labels, canaries, raw held-out responses, provider keys, or product credentials.
- A human review comment is candidate evidence, not an answer key. Gold findings
  require a trigger, impact, and independent proof or explicit expert disposition.
- Historical releases and official results are immutable. Correct mistakes with a
  new version and a disposition; never silently rewrite a published record.
- Keep model-in-fixed-harness and end-to-end-product results in separate tracks.
- Treat unmatched plausible findings as pending adjudication, not automatically
  false. Clean controls remain part of the primary quality report.
- Pin source revisions, model/provider identity, prompt/context/budget identity,
  scorer version, and attempt count in official run records.
- CI actions must be SHA-pinned. Tests and schemas are executable contracts.

## Source layout

- `schemas/` — public interchange contracts.
- `src/review_benchmark/` — validation and offline scoring.
- `fixtures/` — public calibration tasks only.
- `results/` — reviewed, public-safe official records and generated snapshots.
- `docs/` — public methodology, contribution, and release policies.

MIT covers repository code. Each imported task must also carry artifact-specific
license and attribution metadata.
