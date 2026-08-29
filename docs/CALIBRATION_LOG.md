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

## 2026-08-28 — public-v0.3 GLM 5.3 Flash smoke

- Run: [review-runner Actions run 33202852276](https://github.com/FlyOverCoderKY/review-runner/actions/runs/33202852276)
- Track: fixed OpenRouter review harness
- Model: `z-ai/glm-5.3-flash`
- Attempts: one per task (below the three-attempt official minimum)
- Tool-turn budget: 50
- Routed provider: Z.AI for both tasks
- Exact provider-reported cost: $0.006339525 total
- End-to-end elapsed time: 195,105 ms planted; 220,566 ms clean

The planted task again matched five of six gold findings. It also restated the
known empty-list defect as missing test coverage, but the v0.3 path constraint
left that duplicate pending. It emitted two other duplicates. The clean control emitted six comments;
evidence review classified them as compatibility-policy speculation, unchanged
base behavior, an out-of-domain extreme, redundant branch coverage, a demand to
test implementation spelling, and a mistaken claim that importing pytest added
a new test-runner dependency.

Disposition: this run remains provisional and is not publishable as v0.3 because
the duplicate and all clean comments were pending. `public-v0.4` broadens the
empty-list gold matcher to recognize test-path restatements as duplicates and
records evidence-backed false-positive adjudications for those six clean-control
comment classes. The source change is unchanged from v0.3, allowing offline
rescoring without another provider call.

## 2026-08-28 — public-v0.4 provider-routing smoke

- Runs: [Together 33226037686](https://github.com/FlyOverCoderKY/review-runner/actions/runs/33226037686)
  and [Z.AI FP8 33226244692](https://github.com/FlyOverCoderKY/review-runner/actions/runs/33226244692)
- Track: fixed OpenRouter review harness
- Model: `z-ai/glm-5.3-flash`
- Attempts: one per task and provider (below the three-attempt official minimum)
- Tool-turn budget: 50
- Exact provider routing: `together` and `z-ai/fp8`
- Pinned action: v1.2.5 at `2b724b2dac814bfc6695377af0c5fc1b95a1091e`
- Pinned benchmark: `94eb7d7efd0a97240df5a3bedb8d28a67c555df0`

Both routes matched five of six planted findings, for 0.8333 positive recall.
Together retained 1.0 macro adjudicated precision and passed the clean control;
Z.AI had 0.5 macro adjudicated precision and failed the clean control with two
known false positives. Together had one pending finding and 1.0 severity
agreement; Z.AI had two pending findings and 0.6 severity agreement.

Together's median end-to-end review time was 110,660 ms and exact
provider-reported cost was $0.01351319. Z.AI's median was 194,311.5 ms and cost
was $0.006536675. Both adapters exited successfully and the combined cost was
$0.020049865, below the $0.10 comparison cap.

Disposition: the exact-provider controls work and the measurements are retained
as calibration evidence. On this two-task, single-attempt smoke, Together was
better on quality and speed while Z.AI was cheaper. The sample is far too small
for a provider ranking or leaderboard claim; a release-scale comparison requires
independent adjudication and repeated attempts.
