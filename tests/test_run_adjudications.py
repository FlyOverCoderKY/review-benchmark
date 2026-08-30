from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from review_benchmark.models import BenchmarkError
from review_benchmark.run_adjudications import (
    PendingFindingBinding,
    RunAdjudicationBinding,
    derive_finding_id,
    derive_finding_sha256,
    document_sha256,
    load_run_adjudications,
    pending_set_sha256,
    reviewer_response_sha256,
)


def _payload() -> tuple[dict[str, object], RunAdjudicationBinding]:
    run_id = "run-1"
    normalized_sha = "8" * 64
    finding_shas = ("a" * 64, "b" * 64)
    pending = (
        PendingFindingBinding(
            derive_finding_id(
                run_id=run_id,
                task_id="task-1",
                attempt_id="attempt-1",
                normalized_attempt_sha256=normalized_sha,
                finding_index=index,
                finding_sha256=finding_sha,
            ),
            "task-1",
            "attempt-1",
            normalized_sha,
            index,
            finding_sha,
        )
        for index, finding_sha in enumerate(finding_shas)
    )
    pending = tuple(sorted(pending))
    binding = RunAdjudicationBinding(
        run_id=run_id,
        manifest_sha256="3" * 64,
        private_score_sha256="4" * 64,
        config_sha256="6" * 64,
        release_id="release-1",
        release_git_sha="7" * 40,
        release_manifest_sha256="5" * 64,
        scorer_git_sha="9" * 40,
        scorer_version="scorer-1",
        pending=pending,
    )
    payload: dict[str, object] = {
        "schema": "review-benchmark/run-adjudications/1",
        "adjudication_id": "adjudication-1",
        "status": "complete",
        "run": {
            "run_id": binding.run_id,
            "manifest_sha256": binding.manifest_sha256,
            "private_score_sha256": binding.private_score_sha256,
            "config_sha256": binding.config_sha256,
            "release_id": binding.release_id,
            "release_git_sha": binding.release_git_sha,
            "release_manifest_sha256": binding.release_manifest_sha256,
            "scorer_git_sha": binding.scorer_git_sha,
            "scorer_version": binding.scorer_version,
        },
        "pending_set_sha256": pending_set_sha256(pending),
        "reviewers": ["reviewer-a", "reviewer-b"],
        "decisions": [],
    }
    reasons = (
        ("reviewer-a", "Independent evidence confirms it."),
        ("reviewer-b", "The trigger and impact reproduce."),
    )
    for item in pending:
        reviews = [
            {
                "reviewer_id": reviewer_id,
                "verdict": "valid_extra",
                "reason": reason,
                "response_sha256": reviewer_response_sha256(
                    finding_id=item.finding_id,
                    reviewer_id=reviewer_id,
                    verdict="valid_extra",
                    reason=reason,
                ),
            }
            for reviewer_id, reason in reasons
        ]
        payload["decisions"].append(
            {
                "finding": item.to_dict(),
                "reviews": reviews,
                "resolution": "valid_extra",
            }
        )
    payload["document_sha256"] = document_sha256(payload)
    return payload, binding


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "overlay.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _reseal(payload: dict[str, object]) -> None:
    for decision in payload.get("decisions", []):
        finding_id = decision["finding"]["finding_id"]
        for review in decision["reviews"]:
            if review.get("reason"):
                review["response_sha256"] = reviewer_response_sha256(
                    finding_id=finding_id,
                    reviewer_id=review["reviewer_id"],
                    verdict=review["verdict"],
                    reason=review["reason"],
                )
    payload["document_sha256"] = document_sha256(payload)


def test_loads_exact_run_bound_two_reviewer_overlay(tmp_path: Path) -> None:
    payload, binding = _payload()
    loaded = load_run_adjudications(
        _write(tmp_path, payload), expected=binding, require_resolved=True
    )
    assert loaded.binding == binding
    assert loaded.reviewers == ("reviewer-a", "reviewer-b")


def test_overlay_normalizes_integral_json_number_finding_index(tmp_path: Path) -> None:
    payload, _ = _payload()
    payload["decisions"][0]["finding"]["finding_index"] = float(
        payload["decisions"][0]["finding"]["finding_index"]
    )
    _reseal(payload)

    loaded = load_run_adjudications(_write(tmp_path, payload))

    assert type(loaded.binding.pending[0].finding_index) is int


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p["reviewers"].reverse(), "sorted"),
        (lambda p: p["decisions"].reverse(), "sorted"),
        (
            lambda p: p["decisions"][0].__setitem__("resolution", "false_positive"),
            "does not match",
        ),
        (
            lambda p: p["decisions"][0]["reviews"][0].__setitem__("reason", ""),
            "non-empty",
        ),
        (
            lambda p: p["decisions"][0]["finding"].__setitem__(
                "finding_index", 9_007_199_254_740_992
            ),
            "integer between",
        ),
        (lambda p: p.__setitem__("unexpected", True), "unexpected"),
    ],
)
def test_rejects_hostile_overlay_shapes(tmp_path: Path, mutation, match: str) -> None:
    payload, _ = _payload()
    mutation(payload)
    _reseal(payload)
    with pytest.raises(BenchmarkError, match=match):
        load_run_adjudications(_write(tmp_path, payload))


def test_rejects_tampering_even_when_structurally_valid(tmp_path: Path) -> None:
    payload, _ = _payload()
    payload["run"]["run_id"] = "other-run"
    with pytest.raises(BenchmarkError, match="document_sha256"):
        load_run_adjudications(_write(tmp_path, payload))


def test_expected_binding_rejects_cross_run_replay(tmp_path: Path) -> None:
    payload, binding = _payload()
    wrong = replace(binding, run_id="other-run")
    with pytest.raises(BenchmarkError, match="immutable run binding"):
        load_run_adjudications(_write(tmp_path, payload), expected=wrong)


def test_unresolved_decision_is_retained_but_not_publishable(tmp_path: Path) -> None:
    payload, _ = _payload()
    payload["decisions"][0]["reviews"][1]["verdict"] = "false_positive"
    payload["decisions"][0]["resolution"] = "disagreement"
    _reseal(payload)
    path = _write(tmp_path, payload)
    load_run_adjudications(path)
    with pytest.raises(BenchmarkError, match="publication-blocking"):
        load_run_adjudications(path, require_resolved=True)


def test_duplicate_origin_cannot_be_aliased_by_another_finding_id(tmp_path: Path) -> None:
    payload, _ = _payload()
    first = payload["decisions"][0]["finding"]
    second = payload["decisions"][1]["finding"]
    second["task_id"] = first["task_id"]
    second["attempt_id"] = first["attempt_id"]
    second["finding_index"] = first["finding_index"]
    _reseal(payload)
    with pytest.raises(BenchmarkError, match="duplicate finding origin"):
        load_run_adjudications(_write(tmp_path, payload))


@pytest.mark.parametrize("verdict", ["oracle_gap", "insufficient_evidence"])
def test_explicit_uncertainty_outcomes_block_publication(
    tmp_path: Path, verdict: str
) -> None:
    payload, _ = _payload()
    for review in payload["decisions"][0]["reviews"]:
        review["verdict"] = verdict
    payload["decisions"][0]["resolution"] = verdict
    _reseal(payload)
    path = _write(tmp_path, payload)
    loaded = load_run_adjudications(path)
    assert loaded.resolutions[0][1] == verdict
    with pytest.raises(BenchmarkError, match="publication-blocking"):
        load_run_adjudications(path, require_resolved=True)


def test_finding_and_response_digest_golden_vectors() -> None:
    finding = {
        "path": "src/café.py",
        "line": 7,
        "severity": "bug",
        "title": "Unicode ☕",
        "detail": "Value 1.0 fails",
    }
    finding_digest = derive_finding_sha256(finding)
    assert finding_digest == "533b7af958d7c185c2fa212040a8ab8bc720bf98f1a01118e376954ad7321f4e"
    finding_id = derive_finding_id(
        run_id="run-golden",
        task_id="task-1",
        attempt_id="attempt-2",
        normalized_attempt_sha256="a" * 64,
        finding_index=3,
        finding_sha256=finding_digest,
    )
    assert finding_id == "2cab60d21988e29b2fc672c39c92d7bbfecf9b296dd36c751140886a508defe2"
    assert reviewer_response_sha256(
        finding_id=finding_id,
        reviewer_id="reviewer-a",
        verdict="valid_extra",
        reason="Reproduced with Unicode ☕.",
    ) == "3f50ba0f8010c1ebdc4c796ea33d0b30ab0c071d567d6615e336786b058859c0"
