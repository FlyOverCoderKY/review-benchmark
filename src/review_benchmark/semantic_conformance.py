"""Blinded human calibration and one-to-one evaluation for semantic matchers."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from review_benchmark.models import BenchmarkError, _json_loads

CORPUS_SCHEMA = "review-benchmark/semantic-conformance-corpus/1"
LABELS_SCHEMA = "review-benchmark/semantic-conformance-labels/1"
DECISIONS_SCHEMA = "review-benchmark/semantic-matcher-decisions/1"
DECISIONS_SCHEMA_V2 = "review-benchmark/semantic-matcher-decisions/2"
DISAGREEMENTS_SCHEMA = "review-benchmark/semantic-conformance-disagreements/1"
EVALUATION_SCHEMA = "review-benchmark/semantic-conformance-evaluation/1"
EVALUATION_SCHEMA_V2 = "review-benchmark/semantic-conformance-evaluation/2"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = _json_loads(path.read_text(encoding="utf-8"), f"{label} {path}")
    except (OSError, UnicodeError) as exc:
        raise BenchmarkError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkError(f"{label} must be a JSON object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BenchmarkError(f"{label} must be a JSON array")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{label} must be a non-empty string")
    return value


def _require_id(value: object, label: str) -> str:
    result = _require_string(value, label)
    if _ID_RE.fullmatch(result) is None:
        raise BenchmarkError(f"{label} must be a normalized identifier")
    return result


def _bounded_string(value: object, label: str, maximum: int) -> str:
    result = _require_string(value, label)
    if len(result) > maximum:
        raise BenchmarkError(f"{label} must contain at most {maximum} characters")
    return result


def _unique(items: Iterable[str], label: str) -> tuple[str, ...]:
    values = tuple(items)
    if len(values) != len(set(values)):
        raise BenchmarkError(f"{label} must not contain duplicate ids")
    return values


def corpus_sha256(corpus: dict[str, Any]) -> str:
    """Hash the semantic content, independent of insignificant JSON formatting."""
    canonical = json.dumps(
        corpus, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_corpus(path: Path) -> dict[str, Any]:
    corpus = _read_object(path, "semantic conformance corpus")
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise BenchmarkError(f"corpus.schema must be {CORPUS_SCHEMA!r}")
    _require_string(corpus.get("corpus_id"), "corpus.corpus_id")
    groups = _require_list(corpus.get("groups"), "corpus.groups")
    if not groups:
        raise BenchmarkError("corpus.groups must not be empty")

    group_ids: list[str] = []
    all_pair_ids: list[str] = []
    for group_index, raw_group in enumerate(groups):
        label = f"corpus.groups[{group_index}]"
        if not isinstance(raw_group, dict):
            raise BenchmarkError(f"{label} must be a JSON object")
        group_ids.append(_require_string(raw_group.get("group_id"), f"{label}.group_id"))
        references = _require_list(
            raw_group.get("reference_findings"), f"{label}.reference_findings"
        )
        candidates = _require_list(
            raw_group.get("candidate_findings"), f"{label}.candidate_findings"
        )
        if not references or not candidates:
            raise BenchmarkError(f"{label} must contain reference and candidate findings")
        if not all(isinstance(item, dict) for item in (*references, *candidates)):
            raise BenchmarkError(f"{label} findings must be JSON objects")
        reference_ids = _unique(
            (
                _require_string(item.get("id"), f"{label}.reference_findings.id")
                for item in references
            ),
            f"{label}.reference_findings",
        )
        candidate_ids = _unique(
            (
                _require_string(item.get("id"), f"{label}.candidate_findings.id")
                for item in candidates
            ),
            f"{label}.candidate_findings",
        )
        pairs = _require_list(raw_group.get("pairs"), f"{label}.pairs")
        edges: list[tuple[str, str]] = []
        for pair_index, pair in enumerate(pairs):
            pair_label = f"{label}.pairs[{pair_index}]"
            if not isinstance(pair, dict):
                raise BenchmarkError(f"{pair_label} must be a JSON object")
            pair_id = _require_string(pair.get("pair_id"), f"{pair_label}.pair_id")
            reference_id = _require_string(pair.get("reference_id"), f"{pair_label}.reference_id")
            candidate_id = _require_string(pair.get("candidate_id"), f"{pair_label}.candidate_id")
            if reference_id not in reference_ids or candidate_id not in candidate_ids:
                raise BenchmarkError(f"{pair_label} refers to a finding outside its group")
            all_pair_ids.append(pair_id)
            edges.append((reference_id, candidate_id))
        _unique(
            (f"{reference}:{candidate}" for reference, candidate in edges),
            f"{label}.pairs",
        )
        expected_edges = {
            (reference_id, candidate_id)
            for reference_id in reference_ids
            for candidate_id in candidate_ids
        }
        if set(edges) != expected_edges:
            raise BenchmarkError(
                f"{label}.pairs must contain the complete reference/candidate edge matrix"
            )
    _unique(group_ids, "corpus.groups")
    _unique(all_pair_ids, "corpus pair ids")
    return corpus


def _stable_order(values: Iterable[dict[str, Any]], *, seed: str, key: str) -> list[dict[str, Any]]:
    return sorted(
        values,
        key=lambda item: hashlib.sha256(f"{seed}:{item[key]}".encode()).digest(),
    )


def build_blinded_labels(
    corpus: dict[str, Any], *, label_set_id: str, reviewer_id: str
) -> dict[str, Any]:
    """Create a deterministic queue with challenge strata and hypotheses withheld."""
    digest = corpus_sha256(corpus)
    seed = f"{corpus['corpus_id']}:{reviewer_id}"
    groups: list[dict[str, Any]] = []
    for source_group in _stable_order(corpus["groups"], seed=seed, key="group_id"):
        group_seed = f"{seed}:{source_group['group_id']}"
        pairs = [
            {**copy.deepcopy(pair), "verdict": None, "rationale": None}
            for pair in _stable_order(source_group["pairs"], seed=group_seed, key="pair_id")
        ]
        groups.append(
            {
                "group_id": source_group["group_id"],
                "reference_findings": copy.deepcopy(source_group["reference_findings"]),
                "candidate_findings": copy.deepcopy(source_group["candidate_findings"]),
                "pairs": pairs,
            }
        )
    return {
        "schema": LABELS_SCHEMA,
        "label_set_id": label_set_id,
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": digest,
        "kind": "independent",
        "status": "in-progress",
        "reviewer_id": reviewer_id,
        "groups": groups,
    }


def _corpus_pairs(corpus: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    return {
        pair["pair_id"]: (group["group_id"], pair["reference_id"], pair["candidate_id"])
        for group in corpus["groups"]
        for pair in group["pairs"]
    }


def _label_verdicts(
    labels: dict[str, Any], corpus: dict[str, Any], *, require_complete: bool
) -> dict[str, str | None]:
    if labels.get("schema") != LABELS_SCHEMA:
        raise BenchmarkError(f"labels.schema must be {LABELS_SCHEMA!r}")
    if labels.get("corpus_id") != corpus["corpus_id"]:
        raise BenchmarkError("labels.corpus_id does not match corpus")
    if labels.get("corpus_sha256") != corpus_sha256(corpus):
        raise BenchmarkError("labels.corpus_sha256 does not match corpus")
    if require_complete and labels.get("status") != "complete":
        raise BenchmarkError("labels.status must be 'complete'")

    expected = _corpus_pairs(corpus)
    corpus_groups = {group["group_id"]: group for group in corpus["groups"]}
    actual: dict[str, str | None] = {}
    group_ids: list[str] = []
    for group in _require_list(labels.get("groups"), "labels.groups"):
        if not isinstance(group, dict):
            raise BenchmarkError("labels.groups entries must be JSON objects")
        group_id = _require_string(group.get("group_id"), "labels.groups.group_id")
        group_ids.append(group_id)
        source_group = corpus_groups.get(group_id)
        if source_group is None:
            raise BenchmarkError(f"labels contain unknown group id {group_id!r}")
        if group.get("reference_findings") != source_group["reference_findings"]:
            raise BenchmarkError(f"labels group {group_id!r} changes reference findings")
        if group.get("candidate_findings") != source_group["candidate_findings"]:
            raise BenchmarkError(f"labels group {group_id!r} changes candidate findings")
        for pair in _require_list(group.get("pairs"), "labels.groups.pairs"):
            if not isinstance(pair, dict):
                raise BenchmarkError("labels pair must be a JSON object")
            pair_id = _require_string(pair.get("pair_id"), "labels pair id")
            endpoints = (group_id, pair.get("reference_id"), pair.get("candidate_id"))
            if expected.get(pair_id) != endpoints:
                raise BenchmarkError(f"labels pair {pair_id!r} does not match corpus")
            if pair_id in actual:
                raise BenchmarkError(f"labels contain duplicate pair id {pair_id!r}")
            verdict = pair.get("verdict")
            if verdict not in {None, "match", "no-match", "insufficient-evidence"}:
                raise BenchmarkError(f"invalid verdict for pair {pair_id!r}")
            if require_complete and verdict is None:
                raise BenchmarkError(f"pair {pair_id!r} has no completed verdict")
            rationale = pair.get("rationale")
            if require_complete and (not isinstance(rationale, str) or not rationale.strip()):
                raise BenchmarkError(f"pair {pair_id!r} has no completed rationale")
            actual[pair_id] = verdict
    _unique(group_ids, "labels.groups")
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise BenchmarkError(f"labels pair set mismatch: missing={missing}, extra={extra}")
    return actual


def load_labels(
    path: Path, corpus: dict[str, Any], *, require_complete: bool = False
) -> dict[str, Any]:
    labels = _read_object(path, "semantic conformance labels")
    _label_verdicts(labels, corpus, require_complete=require_complete)
    return labels


def _decision_verdicts(decisions: dict[str, Any], corpus: dict[str, Any]) -> dict[str, str]:
    schema = decisions.get("schema")
    if schema not in {DECISIONS_SCHEMA, DECISIONS_SCHEMA_V2}:
        raise BenchmarkError(
            f"decisions.schema must be one of {(DECISIONS_SCHEMA, DECISIONS_SCHEMA_V2)}"
        )
    if schema == DECISIONS_SCHEMA:
        if decisions.get("corpus_id") != corpus["corpus_id"]:
            raise BenchmarkError("decisions.corpus_id does not match corpus")
        if decisions.get("corpus_sha256") != corpus_sha256(corpus):
            raise BenchmarkError("decisions.corpus_sha256 does not match corpus")
        expected = _corpus_pairs(corpus)
        actual: dict[str, str] = {}
        for item in _require_list(decisions.get("decisions"), "decisions.decisions"):
            if not isinstance(item, dict):
                raise BenchmarkError("matcher decision must be a JSON object")
            pair_id = _require_string(item.get("pair_id"), "matcher decision pair_id")
            verdict = item.get("verdict")
            if verdict not in {"match", "no-match"}:
                raise BenchmarkError(f"invalid matcher verdict for pair {pair_id!r}")
            if pair_id in actual:
                raise BenchmarkError(
                    f"matcher decisions contain duplicate pair id {pair_id!r}"
                )
            actual[pair_id] = verdict
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise BenchmarkError(
                f"matcher pair set mismatch: missing={missing}, extra={extra}"
            )
        return actual

    expected_top = {
        "schema",
        "decision_set_id",
        "corpus_id",
        "corpus_sha256",
        "matcher",
        "decisions",
    }
    if set(decisions) != expected_top:
        raise BenchmarkError("decisions must contain exactly the documented top-level fields")
    if decisions.get("corpus_id") != corpus["corpus_id"]:
        raise BenchmarkError("decisions.corpus_id does not match corpus")
    if decisions.get("corpus_sha256") != corpus_sha256(corpus):
        raise BenchmarkError("decisions.corpus_sha256 does not match corpus")
    expected = _corpus_pairs(corpus)
    actual: dict[str, str] = {}
    _require_id(decisions.get("decision_set_id"), "decisions.decision_set_id")
    _require_id(decisions.get("corpus_id"), "decisions.corpus_id")
    matcher = decisions.get("matcher")
    if not isinstance(matcher, dict) or set(matcher) != {"name", "version"}:
        raise BenchmarkError("decisions.matcher must contain exactly name and version")
    _bounded_string(matcher.get("name"), "decisions.matcher.name", 200)
    _bounded_string(matcher.get("version"), "decisions.matcher.version", 200)
    previous_pair_id: str | None = None
    for item in _require_list(decisions.get("decisions"), "decisions.decisions"):
        if not isinstance(item, dict):
            raise BenchmarkError("matcher decision must be a JSON object")
        required = {"pair_id", "verdict", "reason"}
        optional = {"score"}
        if not required <= set(item) or set(item) - required - optional:
            raise BenchmarkError("matcher decision has missing or unexpected fields")
        pair_id = _require_id(item.get("pair_id"), "matcher decision pair_id")
        if previous_pair_id is not None and pair_id <= previous_pair_id:
            raise BenchmarkError("matcher decisions must be unique and sorted by pair_id")
        previous_pair_id = pair_id
        verdict = item.get("verdict")
        allowed = {"match", "no-match", "abstain"}
        if verdict not in allowed:
            raise BenchmarkError(f"invalid matcher verdict for pair {pair_id!r}")
        reason = _require_string(
            item.get("reason"), f"matcher decision {pair_id!r} reason"
        )
        if len(reason) > 4000:
            raise BenchmarkError(f"matcher decision {pair_id!r} reason is too long")
        score = item.get("score")
        if "score" in item and score is None:
            raise BenchmarkError(f"invalid matcher score for pair {pair_id!r}")
        if score is not None and (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= score <= 1
        ):
            raise BenchmarkError(f"invalid matcher score for pair {pair_id!r}")
        actual[pair_id] = verdict
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise BenchmarkError(f"matcher pair set mismatch: missing={missing}, extra={extra}")
    return actual


def load_matcher_decisions(path: Path, corpus: dict[str, Any]) -> dict[str, Any]:
    decisions = _read_object(path, "semantic matcher decisions")
    _decision_verdicts(decisions, corpus)
    return decisions


def build_disagreements(
    corpus: dict[str, Any], label_sets: tuple[dict[str, Any], ...], *, disagreement_set_id: str
) -> dict[str, Any]:
    if len(label_sets) < 2:
        raise BenchmarkError("at least two independent label sets are required")
    verdict_sets: list[dict[str, str | None]] = []
    label_set_ids: list[str] = []
    for labels in label_sets:
        if labels.get("kind") != "independent":
            raise BenchmarkError("disagreement sources must be independent label sets")
        verdict_sets.append(_label_verdicts(labels, corpus, require_complete=True))
        label_set_ids.append(_require_string(labels.get("label_set_id"), "labels.label_set_id"))
    _unique(label_set_ids, "source label sets")

    by_pair = _corpus_pairs(corpus)
    disagreements: list[dict[str, Any]] = []
    for pair_id in sorted(by_pair):
        verdicts = [values[pair_id] for values in verdict_sets]
        if len(set(verdicts)) == 1:
            continue
        decisions = []
        for labels, verdict in zip(label_sets, verdicts, strict=True):
            pair = next(
                pair
                for group in labels["groups"]
                for pair in group["pairs"]
                if pair["pair_id"] == pair_id
            )
            decisions.append(
                {
                    "label_set_id": labels["label_set_id"],
                    "verdict": verdict,
                    "rationale": pair["rationale"],
                }
            )
        disagreements.append(
            {
                "pair_id": pair_id,
                "decisions": decisions,
                "adjudicated_verdict": None,
                "adjudicator_rationale": None,
            }
        )
    return {
        "schema": DISAGREEMENTS_SCHEMA,
        "disagreement_set_id": disagreement_set_id,
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": corpus_sha256(corpus),
        "source_label_set_ids": label_set_ids,
        "status": "open",
        "disagreements": disagreements,
    }


def _pair_payload(labels: dict[str, Any], pair_id: str) -> dict[str, Any]:
    return next(
        pair for group in labels["groups"] for pair in group["pairs"] if pair["pair_id"] == pair_id
    )


def build_adjudicated_labels(
    corpus: dict[str, Any],
    label_sets: tuple[dict[str, Any], ...],
    disagreements: dict[str, Any],
    *,
    label_set_id: str,
    adjudicator_id: str,
) -> dict[str, Any]:
    """Combine unanimous labels with explicitly resolved human disagreements."""
    expected_open = build_disagreements(
        corpus, label_sets, disagreement_set_id="expected-disagreements"
    )
    if disagreements.get("schema") != DISAGREEMENTS_SCHEMA:
        raise BenchmarkError(f"disagreements.schema must be {DISAGREEMENTS_SCHEMA!r}")
    if disagreements.get("corpus_id") != corpus["corpus_id"]:
        raise BenchmarkError("disagreements.corpus_id does not match corpus")
    if disagreements.get("corpus_sha256") != corpus_sha256(corpus):
        raise BenchmarkError("disagreements.corpus_sha256 does not match corpus")
    if disagreements.get("status") != "resolved":
        raise BenchmarkError("disagreements.status must be 'resolved'")
    expected_source_ids = set(expected_open["source_label_set_ids"])
    if set(disagreements.get("source_label_set_ids", [])) != expected_source_ids:
        raise BenchmarkError("disagreement source label sets do not match supplied labels")

    expected_disputed = {item["pair_id"] for item in expected_open["disagreements"]}
    resolved_items = _require_list(
        disagreements.get("disagreements"), "disagreements.disagreements"
    )
    resolved: dict[str, tuple[str, str]] = {}
    for item in resolved_items:
        if not isinstance(item, dict):
            raise BenchmarkError("disagreement entries must be JSON objects")
        pair_id = _require_string(item.get("pair_id"), "disagreement.pair_id")
        verdict = item.get("adjudicated_verdict")
        rationale = item.get("adjudicator_rationale")
        if verdict not in {"match", "no-match", "insufficient-evidence"}:
            raise BenchmarkError(f"disagreement {pair_id!r} has no adjudicated verdict")
        if not isinstance(rationale, str) or not rationale.strip():
            raise BenchmarkError(f"disagreement {pair_id!r} has no adjudicator rationale")
        if pair_id in resolved:
            raise BenchmarkError(f"duplicate resolved disagreement {pair_id!r}")
        resolved[pair_id] = (verdict, rationale)
    if set(resolved) != expected_disputed:
        raise BenchmarkError("resolved disagreement set does not match independent labels")

    verdict_sets = [_label_verdicts(labels, corpus, require_complete=True) for labels in label_sets]
    adjudicated = build_blinded_labels(
        corpus, label_set_id=label_set_id, reviewer_id=adjudicator_id
    )
    adjudicated["kind"] = "adjudicated"
    adjudicated["status"] = "complete"
    for group in adjudicated["groups"]:
        for pair in group["pairs"]:
            pair_id = pair["pair_id"]
            if pair_id in resolved:
                verdict, rationale = resolved[pair_id]
            else:
                verdict = verdict_sets[0][pair_id]
                rationale = _pair_payload(label_sets[0], pair_id)["rationale"]
            pair["verdict"] = verdict
            pair["rationale"] = rationale
    return adjudicated


def _maximum_assignment(group: dict[str, Any], accepted_pair_ids: set[str]) -> set[str]:
    """Return a deterministic maximum-cardinality one-to-one edge assignment."""
    pair_by_edge = {
        (pair["candidate_id"], pair["reference_id"]): pair["pair_id"]
        for pair in group["pairs"]
        if pair["pair_id"] in accepted_pair_ids
    }
    edges: dict[str, list[str]] = {}
    for candidate_id, reference_id in sorted(pair_by_edge):
        edges.setdefault(candidate_id, []).append(reference_id)
    reference_to_candidate: dict[str, str] = {}

    def augment(candidate_id: str, seen: set[str]) -> bool:
        for reference_id in edges.get(candidate_id, []):
            if reference_id in seen:
                continue
            seen.add(reference_id)
            current = reference_to_candidate.get(reference_id)
            if current is None or augment(current, seen):
                reference_to_candidate[reference_id] = candidate_id
                return True
        return False

    for candidate_id in sorted(edges):
        augment(candidate_id, set())
    return {
        pair_by_edge[(candidate_id, reference_id)]
        for reference_id, candidate_id in reference_to_candidate.items()
    }


def evaluate_matcher(
    corpus: dict[str, Any], decisions: dict[str, Any], labels: dict[str, Any]
) -> dict[str, Any]:
    if labels.get("kind") != "adjudicated":
        raise BenchmarkError("evaluation requires a completed adjudicated label set")
    human = _label_verdicts(labels, corpus, require_complete=True)
    predicted = _decision_verdicts(decisions, corpus)

    pair_counts = {
        "true_match": 0,
        "false_match": 0,
        "true_no_match": 0,
        "false_no_match": 0,
        "insufficient_evidence": 0,
        "matcher_abstain": 0,
    }
    for pair_id, human_verdict in human.items():
        predicted_verdict = predicted[pair_id]
        predicted_match = predicted_verdict == "match"
        if human_verdict == "insufficient-evidence":
            pair_counts["insufficient_evidence"] += 1
        elif predicted_verdict == "abstain":
            pair_counts["matcher_abstain"] += 1
        elif human_verdict == "match" and predicted_match:
            pair_counts["true_match"] += 1
        elif human_verdict == "match":
            pair_counts["false_no_match"] += 1
        elif predicted_match:
            pair_counts["false_match"] += 1
        else:
            pair_counts["true_no_match"] += 1

    human_assignment_count = 0
    predicted_assignment_count = 0
    common_assignment_count = 0
    group_results: list[dict[str, Any]] = []
    for group in corpus["groups"]:
        pair_ids = {pair["pair_id"] for pair in group["pairs"]}
        human_edges = {pair_id for pair_id in pair_ids if human[pair_id] == "match"}
        predicted_edges = {
            pair_id
            for pair_id in pair_ids
            if human[pair_id] != "insufficient-evidence" and predicted[pair_id] == "match"
        }
        human_assignment = _maximum_assignment(group, human_edges)
        predicted_assignment = _maximum_assignment(group, predicted_edges)
        common_assignment = _maximum_assignment(group, human_edges & predicted_edges)
        human_assignment_count += len(human_assignment)
        predicted_assignment_count += len(predicted_assignment)
        common_assignment_count += len(common_assignment)
        group_results.append(
            {
                "group_id": group["group_id"],
                "stratum": group["stratum"],
                "human_maximum": len(human_assignment),
                "matcher_maximum": len(predicted_assignment),
                "common_maximum": len(common_assignment),
            }
        )

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    evaluable = (
        pair_counts["true_match"]
        + pair_counts["false_match"]
        + pair_counts["true_no_match"]
        + pair_counts["false_no_match"]
        + pair_counts["matcher_abstain"]
    )
    decided = evaluable - pair_counts["matcher_abstain"]
    pair_correct = pair_counts["true_match"] + pair_counts["true_no_match"]

    assignment = {
        "human_maximum": human_assignment_count,
        "matcher_maximum": predicted_assignment_count,
        "common_maximum": common_assignment_count,
        "precision": ratio(common_assignment_count, predicted_assignment_count),
        "recall": ratio(common_assignment_count, human_assignment_count),
    }
    if decisions.get("schema") == DECISIONS_SCHEMA:
        return {
            "schema": EVALUATION_SCHEMA,
            "corpus_id": corpus["corpus_id"],
            "corpus_sha256": corpus_sha256(corpus),
            "decision_set_id": decisions.get("decision_set_id"),
            "label_set_id": labels.get("label_set_id"),
            "pair_classification": {
                key: value
                for key, value in pair_counts.items()
                if key != "matcher_abstain"
            }
            | {
                "evaluable": evaluable,
                "accuracy": ratio(pair_correct, evaluable),
            },
            "one_to_one_assignment": assignment,
            "groups": group_results,
        }

    _require_id(labels.get("label_set_id"), "labels.label_set_id")
    pair_to_stratum = {
        pair["pair_id"]: group["stratum"]
        for group in corpus["groups"]
        for pair in group["pairs"]
    }
    positive_strata = {"equivalent-paraphrase", "duplicate-restatement"}
    negative_strata = {"related-distinct", "unrelated", "adversarial-keyword-overlap"}

    def critical_gate(strata: set[str], expected_verdict: str) -> dict[str, object]:
        pair_ids = [
            pair_id
            for pair_id, human_verdict in human.items()
            if pair_to_stratum[pair_id] in strata
            and human_verdict != "insufficient-evidence"
            and human_verdict == expected_verdict
        ]
        abstained = sum(predicted[pair_id] == "abstain" for pair_id in pair_ids)
        incorrect = sum(
            predicted[pair_id] not in {expected_verdict, "abstain"} for pair_id in pair_ids
        )
        return {
            "pairs": len(pair_ids),
            "abstained": abstained,
            "incorrect": incorrect,
            "passed": bool(pair_ids) and abstained == 0 and incorrect == 0,
        }

    positive_gate = critical_gate(positive_strata, "match")
    negative_gate = critical_gate(negative_strata, "no-match")
    minimum_precision = 0.95
    minimum_recall = 0.95
    assignment_precision = assignment["precision"]
    assignment_recall = assignment["recall"]
    assignment_eligible = (
        human_assignment_count > 0
        and predicted_assignment_count > 0
        and assignment_precision is not None
        and assignment_recall is not None
    )
    assignment_gate = {
        "eligible": assignment_eligible,
        "minimum_precision": minimum_precision,
        "minimum_recall": minimum_recall,
        "actual_precision": assignment_precision,
        "actual_recall": assignment_recall,
        "passed": bool(
            assignment_eligible
            and assignment_precision >= minimum_precision
            and assignment_recall >= minimum_recall
        ),
    }
    return {
        "schema": EVALUATION_SCHEMA_V2,
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": corpus_sha256(corpus),
        "decision_set_id": decisions.get("decision_set_id"),
        "label_set_id": labels.get("label_set_id"),
        "pair_classification": {
            **pair_counts,
            "evaluable": evaluable,
            "decided": decided,
            "accuracy": ratio(pair_correct, decided),
        },
        "decision_coverage": {
            "total_pairs": len(human),
            "human_insufficient_evidence": pair_counts["insufficient_evidence"],
            "evaluable_pairs": evaluable,
            "decided_pairs": decided,
            "abstained_pairs": pair_counts["matcher_abstain"],
            "decided_coverage": ratio(decided, evaluable),
            "abstention_rate": ratio(pair_counts["matcher_abstain"], evaluable),
        },
        "critical_gates": {
            "identity_matches": positive_gate,
            "distinct_defects": negative_gate,
            "assignment": assignment_gate,
            "passed": (
                positive_gate["passed"]
                and negative_gate["passed"]
                and assignment_gate["passed"]
            ),
        },
        "one_to_one_assignment": assignment,
        "groups": group_results,
    }
