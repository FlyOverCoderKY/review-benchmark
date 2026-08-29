# Methodology

Status: pilot. This document distinguishes implemented behavior from planned work.

## Evaluation constitution

The benchmark measures whether an automated reviewer identifies and explains
evidence-backed defects in frozen pull-request changes under a declared context,
tool, prompt, budget, and repetition policy. It does not measure general software
engineering ability, prove production safety, or establish that one score transfers
to every repository or team preference.

The evaluation unit is an underlying finding within a review task. Task-macro
aggregates prevent one dense PR from dominating. Model-in-fixed-harness and
end-to-end-product results are different tracks and are never directly pooled.
Multi-axis task metadata supplies overlapping coverage slices only: every unique
task ID retains one task-macro weight regardless of how many languages,
frameworks, services, artifacts, tracks, or surfaces tag it.

## Task and gold construction

A task contains an exact diff, inert checkout, metadata, permitted context, and
zero or more hidden gold findings. Human review comments are discovery leads.
Admission requires a concrete defect statement, trigger, impact, and independent
proof such as a regression test, fixing commit plus boundary argument, primary
specification, reproducible trace, or explicit multi-reviewer disposition.

Public sources must carry artifact-specific license and attribution metadata.
Related tasks, revisions, and clean twins share a family ID and remain in one split.

## Matching and incomplete gold sets

The implemented pilot scorer validates structured findings and performs maximum
one-to-one matching against versioned rules. A second comment about an already
matched issue is a duplicate, not extra recall. Unmatched findings are classified
by curated rules as `valid_extra` or `false_positive`; everything else is `pending`
for adjudication. Pending does not silently become false merely because the gold
set is incomplete.

The current regex-backed matcher is a calibration mechanism, not the final oracle
for natural real-PR findings. Before an official real-PR release, semantic matching
will be calibrated against blinded human decisions and a public conformance suite.

## Metrics and ordering

Primary quality reporting includes bug/risk/nit recall, task-macro recall,
adjudicated precision, duplicate rate, pending/noise rate, clean-control pass rate,
severity agreement, and detection frequency across attempts. Operational outcomes
remain separate: malformed output, refusal, truncation, budget exhaustion,
provider failure, adapter failure, judge failure, and runner failure.

Official pilot runs require at least three attempts per task/configuration. The
site presents quality first, then latency, then cost. Unknown cost is `null`, never
zero. Different context, prompt, tools, budgets, provider routing, scorer, judge, or
release identities are not directly ranked.

## Public/private and contamination

Public calibration tasks are assumed contaminated. A hidden label on public code
is held out from users but is not genuinely secret from model training. Private
releases therefore combine recent hidden-label tasks with fresh mutations and,
when available, unpublished owned or partner cases. Every private run records
which endpoint received which cohort and the provider retention policy at that
time.

Releases are immutable. Exposure, oracle defects, scorer changes, or takedowns
create a new release and a historical disposition rather than an in-place rewrite.

## Publication

Raw held-out prompts, outputs, labels, locations, canaries, and judge deliberations
remain private. A versioned allowlist distills aggregate public records. Official
results enter this repository through a reviewed pull request; a merge dispatches
the exact source SHA to the static site, which imports it through another reviewed
pull request.
