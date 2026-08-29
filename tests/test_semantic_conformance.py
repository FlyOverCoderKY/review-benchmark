from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from review_benchmark.models import BenchmarkError
from review_benchmark.semantic_conformance import (
    _maximum_assignment,
    build_adjudicated_labels,
    build_blinded_labels,
    build_disagreements,
    corpus_sha256,
    evaluate_matcher,
    load_corpus,
)

ROOT = Path(__file__).parents[1]
CORPUS_PATH = ROOT / "fixtures" / "semantic-conformance-v0.1" / "corpus.json"


def _schema(name: str) -> dict[str, object]:
    payload = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    Draft202012Validator.check_schema(payload)
    return payload


def _complete(
    queue: dict[str, object], verdicts: dict[str, str], *, kind: str = "independent"
) -> dict[str, object]:
    completed = copy.deepcopy(queue)
    completed["kind"] = kind
    completed["status"] = "complete"
    for group in completed["groups"]:
        for pair in group["pairs"]:
            pair["verdict"] = verdicts.get(pair["pair_id"], "no-match")
            pair["rationale"] = "Synthetic test disposition."
    return completed


def _matcher_decisions(corpus: dict[str, object], matched: set[str]) -> dict[str, object]:
    return {
        "schema": "review-benchmark/semantic-matcher-decisions/1",
        "decision_set_id": "matcher-test-v1",
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": corpus_sha256(corpus),
        "matcher": {"name": "test-matcher", "version": "1"},
        "decisions": [
            {
                "pair_id": pair["pair_id"],
                "verdict": "match" if pair["pair_id"] in matched else "no-match",
            }
            for group in corpus["groups"]
            for pair in group["pairs"]
        ],
    }


def test_public_corpus_has_sixty_pairs_and_all_required_strata() -> None:
    corpus = load_corpus(CORPUS_PATH)
    strata = Counter(group["stratum"] for group in corpus["groups"])
    pair_count = sum(len(group["pairs"]) for group in corpus["groups"])

    assert pair_count == 60
    assert strata == {
        "equivalent-paraphrase": 6,
        "related-distinct": 6,
        "unrelated": 6,
        "duplicate-restatement": 3,
        "bundled-defects": 3,
        "right-defect-wrong-location": 6,
        "partial-trigger-impact": 6,
        "severity-disagreement": 6,
        "valid-out-of-diff": 6,
        "adversarial-keyword-overlap": 6,
    }
    assert corpus["provenance"]["contains_private_task_material"] is False
    Draft202012Validator(_schema("semantic-conformance-corpus.schema.json")).validate(corpus)


def test_blinded_queue_omits_strata_and_has_no_prefilled_human_decisions() -> None:
    corpus = load_corpus(CORPUS_PATH)
    queue = build_blinded_labels(corpus, label_set_id="reviewer-a-v1", reviewer_id="reviewer-a")

    serialized = json.dumps(queue)
    assert "stratum" not in serialized
    assert "equivalent-paraphrase" not in serialized
    assert queue["status"] == "in-progress"
    assert all(
        pair["verdict"] is None and pair["rationale"] is None
        for group in queue["groups"]
        for pair in group["pairs"]
    )
    Draft202012Validator(_schema("semantic-conformance-labels.schema.json")).validate(queue)


def test_disagreement_queue_contains_only_differences_and_no_adjudication() -> None:
    corpus = load_corpus(CORPUS_PATH)
    queue_a = build_blinded_labels(corpus, label_set_id="reviewer-a-v1", reviewer_id="reviewer-a")
    queue_b = build_blinded_labels(corpus, label_set_id="reviewer-b-v1", reviewer_id="reviewer-b")
    first_pair = corpus["groups"][0]["pairs"][0]["pair_id"]
    labels_a = _complete(queue_a, {first_pair: "match"})
    labels_b = _complete(queue_b, {})

    disagreements = build_disagreements(
        corpus,
        (labels_a, labels_b),
        disagreement_set_id="human-disagreements-v1",
    )

    assert disagreements["status"] == "open"
    assert [item["pair_id"] for item in disagreements["disagreements"]] == [first_pair]
    assert disagreements["disagreements"][0]["adjudicated_verdict"] is None
    Draft202012Validator(_schema("semantic-conformance-disagreements.schema.json")).validate(
        disagreements
    )

    disagreements["status"] = "resolved"
    disagreements["disagreements"][0]["adjudicated_verdict"] = "match"
    disagreements["disagreements"][0]["adjudicator_rationale"] = (
        "The candidate describes the same trigger and impact."
    )
    adjudicated = build_adjudicated_labels(
        corpus,
        (labels_a, labels_b),
        disagreements,
        label_set_id="adjudicated-v1",
        adjudicator_id="adjudicator-a",
    )

    assert adjudicated["kind"] == "adjudicated"
    assert adjudicated["status"] == "complete"
    resolved_pair = next(
        pair
        for group in adjudicated["groups"]
        for pair in group["pairs"]
        if pair["pair_id"] == first_pair
    )
    assert resolved_pair["verdict"] == "match"
    Draft202012Validator(_schema("semantic-conformance-labels.schema.json")).validate(adjudicated)


def test_evaluation_uses_maximum_one_to_one_assignment_for_duplicates_and_bundles() -> None:
    corpus = load_corpus(CORPUS_PATH)
    queue = build_blinded_labels(corpus, label_set_id="adjudicated-v1", reviewer_id="adjudicator-a")
    duplicate_group = next(
        group for group in corpus["groups"] if group["stratum"] == "duplicate-restatement"
    )
    bundled_group = next(
        group for group in corpus["groups"] if group["stratum"] == "bundled-defects"
    )
    accepted = {
        pair["pair_id"] for group in (duplicate_group, bundled_group) for pair in group["pairs"]
    }
    labels = _complete(
        queue,
        {pair_id: "match" for pair_id in accepted},
        kind="adjudicated",
    )
    decisions = _matcher_decisions(corpus, accepted)

    result = evaluate_matcher(corpus, decisions, labels)

    assert result["pair_classification"]["true_match"] == 4
    assert result["pair_classification"]["accuracy"] == 1.0
    assert result["one_to_one_assignment"] == {
        "human_maximum": 2,
        "matcher_maximum": 2,
        "common_maximum": 2,
        "precision": 1.0,
        "recall": 1.0,
    }
    Draft202012Validator(_schema("semantic-conformance-evaluation.schema.json")).validate(result)


def test_maximum_assignment_reassigns_a_broad_early_candidate() -> None:
    group = {
        "pairs": [
            {"pair_id": "p11", "reference_id": "ref1", "candidate_id": "can1"},
            {"pair_id": "p12", "reference_id": "ref2", "candidate_id": "can1"},
            {"pair_id": "p21", "reference_id": "ref1", "candidate_id": "can2"},
            {"pair_id": "p22", "reference_id": "ref2", "candidate_id": "can2"},
        ]
    }

    assignment = _maximum_assignment(group, {"p11", "p12", "p21"})

    assert assignment == {"p12", "p21"}


def test_evaluation_rejects_unadjudicated_human_labels() -> None:
    corpus = load_corpus(CORPUS_PATH)
    queue = build_blinded_labels(corpus, label_set_id="reviewer-a-v1", reviewer_id="reviewer-a")
    labels = _complete(queue, {})

    with pytest.raises(BenchmarkError, match="adjudicated"):
        evaluate_matcher(corpus, _matcher_decisions(corpus, set()), labels)
