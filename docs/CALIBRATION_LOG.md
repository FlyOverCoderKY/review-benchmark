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
