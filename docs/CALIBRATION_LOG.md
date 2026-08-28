# Calibration log

Calibration runs are diagnostic and never enter the official leaderboard. They
may expose task, oracle, matcher, adapter, or telemetry defects. Corrections
produce a new immutable release; results from different release identities are
not directly compared.

## 2026-08-28 — public-v0.1 GLM 5.3 Flash smoke

- Run: [review-runner Actions run 33193743531](https://github.com/FlyOverCoderKY/review-runner/actions/runs/33193743531)
- Track: fixed OpenRouter review harness
- Model: `z-ai/glm-5.3-flash`
- Attempts: one per task (below the three-attempt official minimum)
- Tool-turn budget: 50
- Routed providers: Wafer for the planted task and Z.AI for the clean control
- Elapsed time: 208,804 ms planted; 182,754 ms clean

The planted task initially matched three of five findings. Correcting an overly
narrow registry matcher raised that to four of five without changing model
output. The model also identified a real loss of report-capping test coverage
that was absent from the v0.1 gold set. The clean control produced eight comments;
manual inspection found that several were legitimate gaps in the supposedly
clean change, so treating them as false positives would have corrupted the
benchmark.

Disposition: this run remains provisional and is not publishable. `public-v0.1`
is retained for provenance. `public-v0.2` adds the independently verified report
test-coverage finding to the gold set and strengthens the clean twin with a
single rules source, explicit year arguments, preserved report assertions, and
edge-case tests. The original harness did not preserve provider-reported cost,
so exact cost for this historical run remains unknown rather than being replaced
by an estimate.

## 2026-08-28 — public-v0.2 GLM 5.3 Flash smoke

- Run: [review-runner Actions run 33201974060](https://github.com/FlyOverCoderKY/review-runner/actions/runs/33201974060)
- Track: fixed OpenRouter review harness
- Model: `z-ai/glm-5.3-flash`
- Attempts: one per task (below the three-attempt official minimum)
- Tool-turn budget: 50
- Routed provider: Z.AI for both tasks
- Exact provider-reported cost: $0.00487508 total
- End-to-end elapsed time: 139,846 ms planted; 155,606 ms clean

The planted task matched five of six gold findings and missed only the stale 2027
cap amount. It emitted one duplicate and one unmatched test-type comment. The
clean control emitted six comments. Manual inspection confirmed that v0.2 had
introduced avoidable compatibility breaks by removing the default `apply_cap`
year and `SUPPORTED_YEARS`; it also left pass-through/boundary behavior and error
messages insufficiently pinned.

Disposition: this run remains provisional and is not publishable. `public-v0.2`
is retained for provenance. `public-v0.3` restores both compatibility contracts,
derives the registry view from the canonical cap table, preserves the existing
unsupported-year exception type, and adds explicit default, boundary, message,
registry, report, and invalid-input tests.
