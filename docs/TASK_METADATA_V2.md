# Task metadata v2

`review-benchmark/task/2` adds multi-axis coverage metadata without changing the
published `review-benchmark/task/1` contract. The v1 schema remains at
`schemas/task.schema.json`; the additive v2 schema is
`schemas/task-v2.schema.json`.

## Compatibility and migration

Published task/1 manifests and release digests are immutable. Do not upgrade a
historical manifest in place, infer new tags into an old release, or regenerate a
published release merely to adopt task/2. Loaders dispatch on the manifest's
`schema` value and accept both versions in the same release format.

Use task/2 for new tasks when multi-axis coverage or version context is known. A
task that corrects or supersedes an older task belongs in a new immutable release
and keeps the normal family/disposition relationship; it does not overwrite the
older task. Consumers using the Python model retain `Task.language`: task/1 reads
the original `language` field, while task/2 derives it from
`coverage.primary.language`. Task/2 additionally exposes typed `coverage`,
`version_context`, and `lifecycle` values. Those values are `None` for task/1.

The public-safe conformance example is
`fixtures/conformance/task-v2/task.json`. It is contract test data, not an
official benchmark release or ranking input.

## Coverage structure

Each task has exactly one `coverage.primary` object containing a `language` and
an `ecosystem`. This is the task's single planning stratum. Other dimensions are
overlapping slice tags:

- `secondary_languages`;
- `frameworks` and `libraries`;
- `data.layers`, `data.databases`, and `data.providers`;
- cloud `provider` entries with provider-specific `services`;
- `artifacts` such as `source`, `css`, `sql`, `iac`, `container`, and
  `workflow-configuration`;
- benchmark `tracks`; and
- rendering or execution `surfaces`, such as `browser`,
  `server-side-rendering`, `control-plane`, or `data-plane`.

Technology values are intentionally not closed enumerations. Every identifier is
lower-case ASCII, 1–80 characters, and uses only alphanumerics separated by `.`,
`_`, or `-`. Arrays are bounded and reject exact duplicates. Cloud providers are
unique within a task, and version components are unique by `(kind, name)`. This
admits new frameworks and services without a schema release while preventing
free-form prose, aliases with inconsistent casing, or unbounded metadata.

Choose one canonical identifier per technology in corpus review. For example,
use `csharp`, `dotnet`, `entity-framework-core`, `sql-server`, `azure`, and
`azure-sql`, rather than mixing display names or abbreviations. Display labels
belong in reporting code, not task manifests.

## Version and lifecycle context

`version_context.as_of` dates the version evidence. Each component records:

- an open normalized `kind`, with common kinds including `runtime`, `framework`,
  `sdk`, `database`, `api`, `cli`, `iac-provider`, and `lockfile`;
- a normalized technology `name`;
- bounded `source` and `target` version strings, referring respectively to the
  base and reviewed target states; and
- optional source/target lifecycle states with their own `as_of` date.

Record unchanged relevant versions by repeating the exact value in `source` and
`target`. Lifecycle identifiers are also open and normalized; useful technology
states include `supported`, `deprecated`, and `unsupported`. The top-level task
`lifecycle` records corpus state and date. Current corpus states are `candidate`,
`active`, `quarantined`, `corrected`, `retired`, and `tombstoned`, but the schema
does not freeze that operational vocabulary.

Dates are strict `YYYY-MM-DD` values. Version strings are bounded to 128 ASCII
characters and may contain the punctuation needed for semantic versions, API
versions, compatibility ranges, editions, and immutable digests. Put explanatory
prose and evidence in the existing source/context records rather than version
identifiers.

## Task-macro counting

Coverage tags describe membership; they never create additional scoring rows. If
`s_t` is the per-task score for unique task ID `t`, the headline task-macro score
is:

```text
(1 / number_of_unique_task_ids) * sum(s_t)
```

An ASP.NET Core task tagged with C#, EF Core, SQL Server, Azure, Bicep, and
control-plane coverage therefore still has weight one. A slice count is the size
of the set of task IDs matching that slice. One task may count once in several
slices, so slice counts are not additive and their sum must never be used as a
headline denominator.

`summarize_task_coverage` implements this audit rule: it deduplicates membership
within every namespaced slice, reports the unique task count separately, and
rejects duplicate task IDs. Scoring continues to operate on the task itself and
does not consume tag counts as weights.
