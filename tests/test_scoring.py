from __future__ import annotations

from pathlib import Path

from review_benchmark.models import (
    Adjudication,
    Finding,
    GoldFinding,
    MatchRule,
    Task,
    load_task,
)
from review_benchmark.scoring import score_findings


def _gold(identifier: str, keyword: str, *, path: str = "app.py") -> GoldFinding:
    return GoldFinding(
        id=identifier,
        title=identifier,
        severity="bug",
        context="diff",
        defect_statement="A concrete defect.",
        trigger="Trigger it.",
        impact="It fails.",
        proof=("test",),
        rule=MatchRule(paths=(path,), keywords=(keyword,)),
    )


def _task(*gold: GoldFinding, adjudications: tuple[Adjudication, ...] = ()) -> Task:
    return Task(
        root=Path("."),
        id="task-1",
        title="Task",
        family_id="family-1",
        origin="planted",
        language="python",
        visibility="public",
        diff_path=Path("diff.patch"),
        checkout_path=Path("checkout"),
        gold=gold,
        adjudications=adjudications,
        manifest={},
    )


def _finding(text: str, *, path: str = "app.py", severity: str = "bug") -> Finding:
    return Finding(path=path, line=10, severity=severity, title=text, detail=text)


def test_maximum_one_to_one_matching_avoids_order_dependent_recall_loss() -> None:
    broad = _gold("G1", "alpha|beta")
    narrow = _gold("G2", "alpha")
    score = score_findings(_task(broad, narrow), (_finding("alpha"), _finding("beta")))
    assert score.recall == 1.0
    assert {gold_id for _, gold_id in score.matched} == {"G1", "G2"}


def test_duplicate_cannot_inflate_recall_or_precision() -> None:
    score = score_findings(
        _task(_gold("G1", "tenant")),
        (_finding("missing tenant guard"), _finding("tenant guard omitted")),
    )
    assert score.recall == 1.0
    assert len(score.duplicates) == 1
    assert score.adjudicated_precision == 0.5


def test_valid_extra_is_not_baseline_coverage_but_counts_for_precision() -> None:
    adjudication = Adjudication(
        id="A1",
        verdict="valid_extra",
        rationale="Independently confirmed.",
        rule=MatchRule(paths=("other.py",), keywords=("overflow",)),
    )
    score = score_findings(
        _task(_gold("G1", "tenant"), adjudications=(adjudication,)),
        (_finding("integer overflow", path="other.py"),),
    )
    assert score.recall == 0.0
    assert score.adjudicated_precision == 1.0
    assert score.valid_extras == ((0, "A1"),)


def test_unmatched_finding_remains_pending() -> None:
    score = score_findings(_task(_gold("G1", "tenant")), (_finding("possible race"),))
    assert score.pending == (0,)
    assert score.adjudicated_precision is None
    assert score.noise_count == 1


def test_clean_control_score_is_the_finding_count() -> None:
    clean = score_findings(_task(), ())
    noisy = score_findings(_task(), (_finding("invented bug"),))
    assert clean.clean is True
    assert noisy.clean is False
    assert noisy.noise_count == 1


def test_public_registry_finding_matches_supported_year_gold() -> None:
    task_root = (
        Path(__file__).parents[1]
        / "fixtures"
        / "public-v0.4"
        / "tasks"
        / "planted-mini"
    )
    task = load_task(task_root)
    finding = Finding(
        path="rules.py",
        line=3,
        severity="nit",
        title=(
            "rules.py SUPPORTED_YEARS not updated; plan-year registry now "
            "disagrees with CAPS"
        ),
        detail=(
            "SUPPORTED_YEARS still declares 2026 while this change adds 2027 "
            "to CAPS, so the two registries diverge."
        ),
    )

    score = score_findings(task, (finding,))

    assert score.matched == ((0, "PM-B5"),)
    assert score.pending == ()


def test_public_report_coverage_finding_matches_latest_gold() -> None:
    task_root = (
        Path(__file__).parents[1]
        / "fixtures"
        / "public-v0.4"
        / "tasks"
        / "planted-mini"
    )
    task = load_task(task_root)
    finding = Finding(
        path="tests/test_calc.py",
        line=26,
        severity="risk",
        title="The replacement report test no longer verifies capping",
        detail=(
            "The old test asserted capped_total, but the replacement checks only "
            "the echoed year and loses coverage of the report's cap calculation."
        ),
    )

    score = score_findings(task, (finding,))

    assert score.matched == ((0, "PM-B6"),)
    assert score.pending == ()


def test_empty_input_test_coverage_restatement_is_a_duplicate() -> None:
    task_root = (
        Path(__file__).parents[1]
        / "fixtures"
        / "public-v0.4"
        / "tasks"
        / "planted-mini"
    )
    task = load_task(task_root)
    findings = (
        Finding(
            path="calc.py",
            line=15,
            severity="risk",
            title="Average crashes on empty input",
            detail="average_contribution([]) raises ZeroDivisionError.",
        ),
        Finding(
            path="tests/test_calc.py",
            line=13,
            severity="nit",
            title="New average has no edge-case coverage",
            detail="No test covers the empty-list ZeroDivisionError path.",
        ),
    )

    score = score_findings(task, findings)

    assert len(score.matched) == 1
    assert len(score.duplicates) == 1
    assert score.matched[0][1] == score.duplicates[0][1] == "PM-B3"
    assert score.pending == ()


def test_v04_clean_calibration_comments_are_fully_adjudicated() -> None:
    task_root = (
        Path(__file__).parents[1]
        / "fixtures"
        / "public-v0.4"
        / "tasks"
        / "planted-mini-clean"
    )
    task = load_task(task_root)
    findings = (
        Finding("calc.py", 6, "risk", "Hardcoded default year 2026 is stale", "default"),
        Finding("calc.py", 8, "nit", "apply_cap accepts negative amounts", "negative"),
        Finding("calc.py", 21, "nit", "Average loses precision for large integer", "overflow"),
        Finding(
            "tests/test_calc.py",
            20,
            "nit",
            "2027 cap boundary is untested",
            "below 8_550",
        ),
        Finding(
            "tests/test_calc.py",
            30,
            "nit",
            "Registry derivation test is tautological",
            "SUPPORTED_YEARS",
        ),
        Finding(
            "tests/test_calc.py",
            1,
            "nit",
            "pytest dependency lacks a manifest",
            "import",
        ),
    )

    score = score_findings(task, findings)

    assert len(score.false_positives) == 6
    assert score.pending == ()
