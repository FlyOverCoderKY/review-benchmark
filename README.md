# review-benchmark

An open, evidence-backed benchmark for automated code review models and products.

The benchmark is being built for [bench.flyovercoder.com](https://bench.flyovercoder.com)
and starts with two evaluation subjects:

- models running inside one frozen OpenRouter review harness; and
- the end-to-end OpenRouter Review Bot and Grok Code Review Bot products.

Those results live on separate tracks because they answer different questions.

## Current status

`v0.4-pilot` is under construction. The public calibration suite and scorer are
usable for harness development, but there is no official leaderboard claim yet.

## Quick start

```bash
python -m review_benchmark validate-release fixtures/public-v0.4
python -m review_benchmark score \
  fixtures/public-v0.4/tasks/planted-mini \
  examples/planted-findings.json
```

The package uses only the Python standard library. For development:

```bash
python -m pip install -e . --group dev
pytest
python scripts/generate_pilot_fixtures.py --check
python scripts/generate_semantic_conformance.py --check
```

## Design commitments

- Review tasks are frozen code changes, not trivia questions.
- A task may contain zero, one, or many gold findings.
- Human review comments seed candidates but are not assumed complete or correct.
- Matching is one-to-one; duplicates cannot inflate recall.
- Unmatched findings are `valid_extra`, `false_positive`, or `pending`, never
  silently all-false.
- Clean/correct twins measure restraint directly.
- Public/private releases and historical result records are immutable.
- Quality and accuracy lead; latency and cost follow.

See [METHODOLOGY.md](METHODOLOGY.md),
[docs/CALIBRATION_LOG.md](docs/CALIBRATION_LOG.md), and
[docs/CONTRIBUTING_TASKS.md](docs/CONTRIBUTING_TASKS.md). The additive
[task metadata v2 contract](docs/TASK_METADATA_V2.md) describes multi-axis
coverage and migration without rewriting task/1 releases. The
[semantic matching conformance protocol](docs/SEMANTIC_MATCHING_CONFORMANCE.md)
provides a public-safe 60-pair corpus, blinded human-label workflow, and
assignment-aware matcher evaluation.

## Repositories

- `review-benchmark` — this public specification, corpus, scorer, and results.
- `review-benchmark-private` — held-out task inputs and adjudication evidence.
- `review-runner` — private official-run orchestration and product adapters.
- `bench.flyovercoder.com` — private-source static leaderboard site.

## License

Repository code is MIT licensed. Imported source artifacts retain their upstream
licenses and attribution; every task manifest must state its redistribution basis.
