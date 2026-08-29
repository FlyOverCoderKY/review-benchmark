"""Command-line interface for validation and offline scoring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from review_benchmark.models import BenchmarkError, load_findings, load_task
from review_benchmark.release import load_release
from review_benchmark.scoring import score_findings
from review_benchmark.semantic_conformance import (
    build_adjudicated_labels,
    build_blinded_labels,
    build_disagreements,
    evaluate_matcher,
    load_corpus,
    load_labels,
    load_matcher_decisions,
)


def _json_dump(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _validate_task(args: argparse.Namespace) -> int:
    task = load_task(Path(args.task))
    _json_dump(
        {
            "valid": True,
            "task_id": task.id,
            "gold_count": len(task.gold),
            "adjudication_count": len(task.adjudications),
        }
    )
    return 0


def _validate_release(args: argparse.Namespace) -> int:
    release = load_release(Path(args.release))
    _json_dump(
        {
            "valid": True,
            "release_id": release.id,
            "visibility": release.visibility,
            "task_count": len(release.tasks),
            "gold_count": sum(len(task.gold) for task in release.tasks),
        }
    )
    return 0


def _score(args: argparse.Namespace) -> int:
    task = load_task(Path(args.task))
    findings = load_findings(Path(args.findings), expected_task_id=task.id)
    payload = score_findings(task, findings).to_dict()
    if args.out:
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    _json_dump(payload)
    return 0


def _write_and_dump(payload: object, destination: str) -> None:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _json_dump(payload)


def _semantic_blind(args: argparse.Namespace) -> int:
    corpus = load_corpus(Path(args.corpus))
    payload = build_blinded_labels(
        corpus, label_set_id=args.label_set_id, reviewer_id=args.reviewer_id
    )
    _write_and_dump(payload, args.out)
    return 0


def _semantic_disagreements(args: argparse.Namespace) -> int:
    corpus = load_corpus(Path(args.corpus))
    labels = tuple(load_labels(Path(path), corpus, require_complete=True) for path in args.labels)
    payload = build_disagreements(corpus, labels, disagreement_set_id=args.disagreement_set_id)
    _write_and_dump(payload, args.out)
    return 0


def _semantic_adjudicate(args: argparse.Namespace) -> int:
    corpus = load_corpus(Path(args.corpus))
    labels = tuple(load_labels(Path(path), corpus, require_complete=True) for path in args.labels)
    disagreements = json.loads(Path(args.disagreements).read_text(encoding="utf-8"))
    payload = build_adjudicated_labels(
        corpus,
        labels,
        disagreements,
        label_set_id=args.label_set_id,
        adjudicator_id=args.adjudicator_id,
    )
    _write_and_dump(payload, args.out)
    return 0


def _semantic_evaluate(args: argparse.Namespace) -> int:
    corpus = load_corpus(Path(args.corpus))
    decisions = load_matcher_decisions(Path(args.decisions), corpus)
    labels = load_labels(Path(args.labels), corpus, require_complete=True)
    payload = evaluate_matcher(corpus, decisions, labels)
    if args.out:
        _write_and_dump(payload, args.out)
    else:
        _json_dump(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_task = sub.add_parser("validate-task", help="validate one frozen review task")
    validate_task.add_argument("task")
    validate_task.set_defaults(handler=_validate_task)
    validate_release = sub.add_parser("validate-release", help="validate an immutable release")
    validate_release.add_argument("release")
    validate_release.set_defaults(handler=_validate_release)
    score = sub.add_parser("score", help="score normalized findings offline")
    score.add_argument("task")
    score.add_argument("findings")
    score.add_argument("--out", default="")
    score.set_defaults(handler=_score)
    semantic_blind = sub.add_parser(
        "semantic-blind", help="create an unlabeled, stratum-blinded human review queue"
    )
    semantic_blind.add_argument("corpus")
    semantic_blind.add_argument("--label-set-id", required=True)
    semantic_blind.add_argument("--reviewer-id", required=True)
    semantic_blind.add_argument("--out", required=True)
    semantic_blind.set_defaults(handler=_semantic_blind)
    semantic_disagreements = sub.add_parser(
        "semantic-disagreements", help="prepare unresolved differences between human label sets"
    )
    semantic_disagreements.add_argument("corpus")
    semantic_disagreements.add_argument("labels", nargs="+")
    semantic_disagreements.add_argument("--disagreement-set-id", required=True)
    semantic_disagreements.add_argument("--out", required=True)
    semantic_disagreements.set_defaults(handler=_semantic_disagreements)
    semantic_adjudicate = sub.add_parser(
        "semantic-adjudicate",
        help="combine independent labels with resolved disagreement decisions",
    )
    semantic_adjudicate.add_argument("corpus")
    semantic_adjudicate.add_argument("disagreements")
    semantic_adjudicate.add_argument("labels", nargs="+")
    semantic_adjudicate.add_argument("--label-set-id", required=True)
    semantic_adjudicate.add_argument("--adjudicator-id", required=True)
    semantic_adjudicate.add_argument("--out", required=True)
    semantic_adjudicate.set_defaults(handler=_semantic_adjudicate)
    semantic_evaluate = sub.add_parser(
        "semantic-evaluate", help="compare matcher decisions with adjudicated human labels"
    )
    semantic_evaluate.add_argument("corpus")
    semantic_evaluate.add_argument("decisions")
    semantic_evaluate.add_argument("labels")
    semantic_evaluate.add_argument("--out", default="")
    semantic_evaluate.set_defaults(handler=_semantic_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
