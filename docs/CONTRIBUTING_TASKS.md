# Contributing review tasks

Open an issue before contributing copied upstream source. A candidate is accepted
only when the license, attribution, exact revisions, defect evidence, and family
relationships can be reviewed.

## Candidate packet

Provide:

1. upstream repository and pull-request URLs;
2. license evidence at the exact base revision;
3. base, buggy head, and fixing commit SHAs;
4. one underlying defect per proposed finding;
5. trigger, impact, and independent proof;
6. minimum context needed to discover it;
7. known clean counterpart or counterevidence; and
8. any author, maintainer, privacy, or redistribution concern.

New tasks should use the additive
[task metadata v2 contract](TASK_METADATA_V2.md) when coverage and version
context are available. Do not migrate a published task/1 manifest in place.

Do not submit secrets, proprietary code, personal data, or a raw review comment as
if it were complete ground truth. Model-assisted discovery is allowed when it is
disclosed; human adjudicators still require independent evidence.

## Lifecycle

Candidates move through `candidate`, `active`, `quarantined`, `corrected`,
`retired`, or `tombstoned`. Broken proof, inaccessible commits, contamination,
rights requests, scorer disagreement, or saturation can quarantine a task. Public
history records the reason and replacement without preserving removed restricted
content.
