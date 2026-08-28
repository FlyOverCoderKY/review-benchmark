"""Command-line interface for validation and offline scoring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from review_benchmark.models import BenchmarkError, load_findings, load_task
from review_benchmark.release import load_release
from review_benchmark.scoring import score_findings


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
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
