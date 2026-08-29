"""Generate the public-safe, intentionally unlabeled semantic matcher corpus."""

# ruff: noqa: E501 -- keeping synthetic finding prose contiguous aids corpus review.

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "fixtures" / "semantic-conformance-v0.1" / "corpus.json"


def case(
    reference_title: str,
    reference_detail: str,
    candidate_title: str,
    candidate_detail: str,
    *,
    reference_path: str = "src/service.py",
    candidate_path: str | None = None,
    reference_severity: str = "bug",
    candidate_severity: str | None = None,
) -> dict[str, str]:
    return {
        "reference_title": reference_title,
        "reference_detail": reference_detail,
        "candidate_title": candidate_title,
        "candidate_detail": candidate_detail,
        "reference_path": reference_path,
        "candidate_path": candidate_path or reference_path,
        "reference_severity": reference_severity,
        "candidate_severity": candidate_severity or reference_severity,
    }


SIMPLE_CASES: dict[str, list[dict[str, str]]] = {
    "equivalent-paraphrase": [
        case(
            "Tenant filter is omitted",
            "The query no longer restricts rows to the active tenant, exposing other tenants' records.",
            "Cross-tenant rows can leak",
            "Because tenant_id is not included in the WHERE clause, a request can return records owned by another tenant.",
            reference_path="src/orders.sql",
        ),
        case(
            "Pagination stops after the first page",
            "The storage listing ignores next_page_token and silently drops objects after page one.",
            "Object traversal is truncated",
            "The loop never consumes the continuation token, so only the first batch of objects is processed.",
            reference_path="src/storage.ts",
        ),
        case(
            "Stale closure overwrites newer state",
            "The delayed callback captures the old count and loses intervening increments.",
            "Timer update uses an obsolete count",
            "setCount(count + 1) runs from a captured render value; a functional update is required to preserve newer increments.",
            reference_path="src/Counter.tsx",
        ),
        case(
            "NOT IN rejects every row when the subquery contains NULL",
            "SQL three-valued logic makes the predicate unknown for all candidates when a NULL appears.",
            "Nullable exclusion list empties the result",
            "A NULL returned by the NOT IN subquery makes every comparison unknown, so eligible rows disappear.",
            reference_path="db/report.sql",
        ),
        case(
            "Focus ring is clipped",
            "overflow: hidden on the card cuts off the keyboard focus outline.",
            "Keyboard focus indicator is not visible",
            "The focused link's outline extends beyond the card and is hidden by the new overflow rule.",
            reference_path="src/card.css",
            reference_severity="risk",
        ),
        case(
            "Audit write is outside the transaction",
            "The transaction commits before the audit record is inserted, so audit failure leaves an untracked update.",
            "Commit can succeed without its audit row",
            "The audit insert runs after commit and cannot roll back the state change when it fails.",
            reference_path="src/account.cs",
        ),
    ],
    "related-distinct": [
        case(
            "Authorization scope is not checked",
            "The endpoint accepts a valid token without requiring the invoices.write scope.",
            "Token cache ignores expiration",
            "Expired access tokens remain in the process cache and can be reused after their expiry.",
            reference_path="src/auth.ts",
        ),
        case(
            "Query materializes tracked entities",
            "A read-only query omits AsNoTracking and grows the change tracker.",
            "Loop issues one query per row",
            "Accessing the navigation property inside the loop creates an N+1 query pattern.",
            reference_path="src/Orders.cs",
            candidate_path="src/Orders.cs",
            reference_severity="risk",
        ),
        case(
            "Server and client render different IDs",
            "Random IDs generated during render cause a hydration mismatch.",
            "Component leaks a resize listener",
            "The effect registers a window listener but its cleanup does not remove it.",
            reference_path="src/Profile.tsx",
        ),
        case(
            "Deployment assumes the commercial-cloud endpoint",
            "The hard-coded endpoint fails in sovereign cloud partitions.",
            "Role lacks permission to read the secret",
            "The workload identity is never granted secret read access.",
            reference_path="infra/main.tf",
        ),
        case(
            "Overlay intercepts button clicks",
            "The overlay's stacking context covers the button and receives pointer events.",
            "Button has no visible keyboard focus",
            "The new reset removes outline without supplying an alternate focus indicator.",
            reference_path="src/dialog.css",
            reference_severity="risk",
        ),
        case(
            "Retries synchronize without jitter",
            "Every client retries on the same exponential schedule, amplifying a thundering herd.",
            "Retried create request is not idempotent",
            "A timeout followed by retry can create the order twice because no idempotency key is sent.",
            reference_path="src/client.py",
            reference_severity="risk",
        ),
    ],
    "unrelated": [
        case(
            "Cache key omits locale",
            "Localized responses collide because locale is absent from the cache key.",
            "Shutdown waits forever for a worker",
            "The worker join has no timeout and can block process termination.",
            reference_path="src/cache.py",
            candidate_path="src/worker.py",
        ),
        case(
            "CSV parser drops quoted newlines",
            "Splitting input by line before parsing corrupts quoted multiline cells.",
            "Password log entry is not redacted",
            "The authentication failure log serializes the supplied password.",
            reference_path="src/importer.go",
            candidate_path="src/login.go",
        ),
        case(
            "Image width can divide by zero",
            "A zero source width reaches the scale calculation.",
            "Database connection is not returned to the pool",
            "The early return skips disposing the connection.",
            reference_path="src/image.rs",
            candidate_path="src/repository.rs",
        ),
        case(
            "Webhook signature compares decoded text",
            "Canonicalizing decoded JSON changes the signed bytes.",
            "CSS grid overflows at 320 pixels",
            "Fixed columns are wider than the narrow viewport.",
            reference_path="src/webhook.js",
            candidate_path="src/layout.css",
        ),
        case(
            "Lease renewal uses local time",
            "Clock changes can move the renewal deadline backward.",
            "Translation key is missing",
            "The French bundle does not contain the newly referenced heading.",
            reference_path="src/lease.cs",
            candidate_path="locales/fr.json",
        ),
        case(
            "Archive extraction permits traversal",
            "An entry containing ../ can escape the destination directory.",
            "Health probe uses the wrong port",
            "The deployment probes 8081 while the container listens on 8080.",
            reference_path="src/archive.java",
            candidate_path="deploy/app.yaml",
        ),
    ],
    "right-defect-wrong-location": [
        case(
            "Requested year is not forwarded",
            "annual_report calls apply_cap without its year argument.",
            "Requested year is not forwarded",
            "The report uses the default year because the call omits the requested year.",
            reference_path="src/report.py",
            candidate_path="src/calc.py",
        ),
        case(
            "Continuation token is discarded",
            "The list loop never assigns the response token for its next request.",
            "Continuation token is discarded",
            "Only the first page is consumed because the response token is ignored.",
            reference_path="src/list.ts",
            candidate_path="src/types.ts",
        ),
        case(
            "Foreign key cascade deletes invoices",
            "The migration changes the invoice relation to ON DELETE CASCADE.",
            "Deleting a customer now deletes invoices",
            "The new cascade removes historical invoices with the customer.",
            reference_path="db/0042_customer.sql",
            candidate_path="src/customer.cs",
        ),
        case(
            "Effect misses accountId dependency",
            "The effect keeps loading the previous account after the prop changes.",
            "Account changes use stale data",
            "The request is not rerun when accountId changes.",
            reference_path="src/Account.tsx",
            candidate_path="src/api.ts",
        ),
        case(
            "IAM condition uses the wrong resource tag key",
            "The condition can never match the tag supplied on the bucket.",
            "Tagged bucket access is always denied",
            "The policy tests a different resource tag name than the bucket defines.",
            reference_path="infra/policy.tf",
            candidate_path="infra/bucket.tf",
        ),
        case(
            "New overflow clips the menu",
            "The menu extends outside its container and is hidden by overflow: hidden.",
            "Dropdown content is clipped",
            "The container's overflow prevents the open menu from being visible.",
            reference_path="src/Menu.css",
            candidate_path="src/Menu.tsx",
            reference_severity="risk",
        ),
    ],
    "partial-trigger-impact": [
        case(
            "Empty average divides by zero",
            "Calling average([]) divides the sum by zero and raises unexpectedly.",
            "Missing empty guard",
            "There is no check for an empty list.",
            reference_path="src/stats.py",
            reference_severity="risk",
        ),
        case(
            "Case-insensitive IDs collide",
            "On a case-insensitive store, creating IDs Foo and foo overwrites the first record.",
            "Identifier normalization is risky",
            "The new normalization may cause collisions.",
            reference_path="src/id.cs",
            reference_severity="risk",
        ),
        case(
            "Retry duplicates payments",
            "When the first response is lost, retrying without an idempotency key charges twice.",
            "Retry has no idempotency key",
            "The payment request does not set one.",
            reference_path="src/payment.ts",
        ),
        case(
            "Fractional seconds are truncated",
            "Serializing timestamps to whole seconds reorders events created within the same second.",
            "Timestamp precision changed",
            "The formatter no longer includes fractional seconds.",
            reference_path="src/events.go",
            reference_severity="risk",
        ),
        case(
            "Focus is trapped behind the modal",
            "Opening the modal leaves keyboard focus on an inert background control.",
            "Modal does not move focus",
            "No focus call is made after opening.",
            reference_path="src/Modal.tsx",
            reference_severity="risk",
        ),
        case(
            "Rollback cannot restore the previous image",
            "The mutable latest tag is overwritten, so a failed rollout has no pinned prior digest.",
            "Deployment uses latest",
            "The image tag is mutable.",
            reference_path="deploy/app.yaml",
            reference_severity="risk",
        ),
    ],
    "severity-disagreement": [
        case(
            "Password is written to logs",
            "The failure path records the plaintext password.",
            "Debug log may include a password",
            "Authentication failures serialize the raw credential.",
            reference_path="src/auth.py",
            candidate_severity="nit",
        ),
        case(
            "Missing tenant predicate leaks data",
            "The query returns records from every tenant.",
            "Tenant filter should be restored",
            "The WHERE clause no longer restricts rows to the current tenant.",
            reference_path="db/orders.sql",
            candidate_severity="risk",
        ),
        case(
            "Cleanup deletes the active directory",
            "The resolved cleanup target points at the current deployment.",
            "Cleanup path seems dangerous",
            "The command can remove the live deployment directory.",
            reference_path="scripts/deploy.ps1",
            candidate_severity="nit",
        ),
        case(
            "Empty input raises ZeroDivisionError",
            "The new average divides by len(items) without guarding zero.",
            "Average needs an empty-input guard",
            "An empty list reaches a zero denominator.",
            reference_path="src/stats.py",
            reference_severity="risk",
            candidate_severity="bug",
        ),
        case(
            "Button focus indicator is removed",
            "Keyboard users cannot see which button is focused.",
            "Outline removal hurts keyboard navigation",
            "outline: none has no replacement style.",
            reference_path="src/button.css",
            reference_severity="risk",
            candidate_severity="nit",
        ),
        case(
            "Retry loop has no upper bound",
            "A persistent provider failure keeps the request alive forever.",
            "Retries can continue forever",
            "There is no attempt or deadline check in the retry loop.",
            reference_path="src/provider.go",
            candidate_severity="risk",
        ),
    ],
    "valid-out-of-diff": [
        case(
            "Registry omits the new plan year",
            "The changed cap table adds 2028 while the repository registry still lists through 2027.",
            "Supported-year registry is stale",
            "The unchanged registry file does not include the year added by this patch.",
            reference_path="src/rules.py",
            candidate_path="src/rules.py",
            reference_severity="risk",
        ),
        case(
            "Changed producer exceeds the consumer limit",
            "The producer now emits 4 MiB messages but the unchanged consumer rejects anything above 1 MiB.",
            "Consumer rejects the new message size",
            "The consumer's unchanged 1 MiB limit is below the producer's new 4 MiB payload.",
            reference_path="src/consumer.cs",
            reference_severity="risk",
        ),
        case(
            "Route conflicts with the existing wildcard",
            "The new /users/me route is captured by the unchanged /users/{id} route first.",
            "Existing parameter route shadows /users/me",
            "Router ordering sends the new literal path to the id handler.",
            reference_path="src/routes.ts",
        ),
        case(
            "Migration exceeds an old column width",
            "The new 64-character identifiers are stored in an unchanged varchar(32) column.",
            "Database column truncates new identifiers",
            "The unchanged schema only allows 32 characters while this change emits 64.",
            reference_path="db/schema.sql",
        ),
        case(
            "New CSP blocks the existing worker",
            "The worker is loaded from a host absent from the new worker-src directive.",
            "Existing worker host is missing from CSP",
            "The new policy prevents the unchanged analytics worker from loading.",
            reference_path="src/analytics.js",
            reference_severity="risk",
        ),
        case(
            "New runtime is unsupported by the deployment image",
            "The project targets runtime 9 but the unchanged container still installs runtime 8 only.",
            "Container cannot launch the new target runtime",
            "The Dockerfile remains on runtime 8 while the project now targets 9.",
            reference_path="Dockerfile",
        ),
    ],
    "adversarial-keyword-overlap": [
        case(
            "Tenant predicate is omitted from the delete",
            "Deleting one tenant's record can remove matching IDs in other tenants.",
            "Tenant predicate is duplicated",
            "The query applies tenant_id twice, which is redundant but does not broaden deletion.",
            reference_path="db/delete.sql",
        ),
        case(
            "Retry duplicates a payment",
            "The retried POST has no idempotency key and can charge twice.",
            "Duplicate retry metrics are emitted",
            "The metric increments both before and after a retry; payment execution remains idempotent.",
            reference_path="src/payment.ts",
        ),
        case(
            "NULL in NOT IN empties the result",
            "A nullable subquery makes every NOT IN comparison unknown.",
            "NULL values are omitted from the JSON result",
            "The serializer suppresses null properties, changing the response shape.",
            reference_path="db/query.sql",
            candidate_path="src/json.cs",
        ),
        case(
            "Focus outline is clipped by overflow",
            "The keyboard indicator extends beyond a hidden-overflow container.",
            "Overflow text receives focus",
            "A long label wraps and increases the tab stop's height; its outline remains visible.",
            reference_path="src/card.css",
        ),
        case(
            "Continuation token is never consumed",
            "Object listing ends after the first page.",
            "Token continuation refreshes authentication",
            "The access-token refresh path continues the request with a new credential.",
            reference_path="src/list.ts",
            candidate_path="src/auth.ts",
        ),
        case(
            "Hydration renders a different timestamp",
            "Server and client call the clock independently while rendering.",
            "Timestamp precision is reduced after hydration",
            "A post-hydration formatter intentionally rounds display values to minutes.",
            reference_path="src/Clock.tsx",
        ),
    ],
}


DUPLICATE_GROUPS = [
    (
        (
            "Negative values are accepted",
            "Removing validation lets negative contributions reduce the total.",
            "src/calc.py",
            "bug",
        ),
        [
            (
                "Negative-input guard was removed",
                "contribution_total now accepts negative elements.",
                "src/calc.py",
                "bug",
            ),
            (
                "Missing validation permits negative totals",
                "A negative contribution silently lowers the result.",
                "tests/test_calc.py",
                "risk",
            ),
        ],
    ),
    (
        (
            "Listing stops at one page",
            "The response continuation token is not consumed.",
            "src/list.go",
            "bug",
        ),
        [
            (
                "Only the first object page is processed",
                "The loop ignores nextPageToken.",
                "src/list.go",
                "bug",
            ),
            (
                "Large buckets are truncated",
                "No second list request is made with the continuation token.",
                "tests/list_test.go",
                "risk",
            ),
        ],
    ),
    (
        (
            "Icon button has no accessible name",
            "The visible glyph supplies no name to assistive technology.",
            "src/IconButton.tsx",
            "risk",
        ),
        [
            (
                "Screen readers announce an unnamed button",
                "The glyph-only control lacks aria-label text.",
                "src/IconButton.tsx",
                "risk",
            ),
            (
                "Accessibility coverage misses the unnamed control",
                "The rendered button exposes an empty accessible name.",
                "tests/IconButton.test.tsx",
                "nit",
            ),
        ],
    ),
]


BUNDLED_GROUPS = [
    (
        [
            (
                "Retry can charge twice",
                "The payment POST has no idempotency key.",
                "src/pay.ts",
                "bug",
            ),
            (
                "Retry loop has no deadline",
                "Persistent failure can keep the request open forever.",
                "src/pay.ts",
                "risk",
            ),
        ],
        (
            "Payment retries are unsafe and unbounded",
            "Retries lack both an idempotency key and an overall deadline.",
            "src/pay.ts",
            "bug",
        ),
    ),
    (
        [
            (
                "Modal does not move focus",
                "Keyboard focus remains behind the modal.",
                "src/Modal.tsx",
                "risk",
            ),
            (
                "Modal does not restore focus",
                "Closing the modal loses the invoking control.",
                "src/Modal.tsx",
                "risk",
            ),
        ],
        (
            "Modal focus lifecycle is broken",
            "Opening leaves focus behind the dialog and closing does not return it to the trigger.",
            "src/Modal.tsx",
            "risk",
        ),
    ),
    (
        [
            (
                "Migration cascades invoice deletion",
                "Deleting a customer now removes invoices.",
                "db/migrate.sql",
                "bug",
            ),
            (
                "Migration cannot roll back",
                "The down migration does not restore the prior foreign key.",
                "db/migrate.sql",
                "risk",
            ),
        ],
        (
            "Invoice migration is destructive and irreversible",
            "It adds a delete cascade and its down path does not restore the old constraint.",
            "db/migrate.sql",
            "bug",
        ),
    ),
]


def finding(identifier: str, item: tuple[str, str, str, str], *, line: int) -> dict[str, object]:
    title, detail, path, severity = item
    return {
        "id": identifier,
        "path": path,
        "line": line,
        "severity": severity,
        "title": title,
        "detail": detail,
    }


def generate_corpus() -> dict[str, object]:
    groups: list[dict[str, object]] = []
    group_number = 0
    pair_number = 0
    finding_number = 0

    def next_finding(prefix: str) -> str:
        nonlocal finding_number
        finding_number += 1
        return f"{prefix}{finding_number:03d}"

    def add_group(
        stratum: str,
        references: list[tuple[str, str, str, str]],
        candidates: list[tuple[str, str, str, str]],
    ) -> None:
        nonlocal group_number, pair_number
        group_number += 1
        reference_findings = [
            finding(next_finding("r"), item, line=10 + index)
            for index, item in enumerate(references)
        ]
        candidate_findings = [
            finding(next_finding("c"), item, line=20 + index)
            for index, item in enumerate(candidates)
        ]
        pairs = []
        for reference in reference_findings:
            for candidate in candidate_findings:
                pair_number += 1
                pairs.append(
                    {
                        "pair_id": f"p{pair_number:03d}",
                        "reference_id": reference["id"],
                        "candidate_id": candidate["id"],
                    }
                )
        groups.append(
            {
                "group_id": f"g{group_number:03d}",
                "stratum": stratum,
                "reference_findings": reference_findings,
                "candidate_findings": candidate_findings,
                "pairs": pairs,
            }
        )

    for stratum, cases in SIMPLE_CASES.items():
        for item in cases:
            add_group(
                stratum,
                [
                    (
                        item["reference_title"],
                        item["reference_detail"],
                        item["reference_path"],
                        item["reference_severity"],
                    )
                ],
                [
                    (
                        item["candidate_title"],
                        item["candidate_detail"],
                        item["candidate_path"],
                        item["candidate_severity"],
                    )
                ],
            )
    for reference, candidates in DUPLICATE_GROUPS:
        add_group("duplicate-restatement", [reference], candidates)
    for references, candidate in BUNDLED_GROUPS:
        add_group("bundled-defects", references, [candidate])

    assert pair_number == 60
    assert group_number == 54
    return {
        "schema": "review-benchmark/semantic-conformance-corpus/1",
        "corpus_id": "semantic-conformance-v0.1",
        "status": "unlabeled",
        "provenance": {
            "kind": "synthetic",
            "license_spdx": "MIT",
            "contains_private_task_material": False,
            "generator": "scripts/generate_semantic_conformance.py",
        },
        "groups": groups,
    }


def render() -> str:
    return json.dumps(generate_corpus(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="semantic-conformance-check.") as temporary:
            generated = Path(temporary) / "corpus.json"
            generated.write_text(rendered, encoding="utf-8", newline="\n")
            if DESTINATION.is_file() and DESTINATION.read_bytes() == generated.read_bytes():
                print("semantic conformance corpus is reproducible")
                return 0
        print("semantic conformance corpus has drifted")
        return 1
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"generated {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
