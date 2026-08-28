"""Deterministic one-to-one scoring with a third state for incomplete gold sets."""

from __future__ import annotations

import re
from dataclasses import dataclass

from review_benchmark.models import Adjudication, Finding, GoldFinding, MatchRule, Task

SCORER_VERSION = "review-benchmark-scorer/1"


def matches(finding: Finding, rule: MatchRule) -> bool:
    if rule.paths and finding.path not in rule.paths:
        return False
    text = f"{finding.title}\n{finding.detail}"
    return any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in rule.keywords
    )


def _maximum_matching(
    findings: tuple[Finding, ...], gold: tuple[GoldFinding, ...]
) -> dict[int, int]:
    edges = {
        finding_index: [
            gold_index
            for gold_index, expected in enumerate(gold)
            if matches(finding, expected.rule)
        ]
        for finding_index, finding in enumerate(findings)
    }
    gold_to_finding: dict[int, int] = {}

    def augment(finding_index: int, seen: set[int]) -> bool:
        for gold_index in edges[finding_index]:
            if gold_index in seen:
                continue
            seen.add(gold_index)
            current = gold_to_finding.get(gold_index)
            if current is None or augment(current, seen):
                gold_to_finding[gold_index] = finding_index
                return True
        return False

    for finding_index in range(len(findings)):
        augment(finding_index, set())
    return {finding_index: gold_index for gold_index, finding_index in gold_to_finding.items()}


def _first_adjudication(
    finding: Finding, adjudications: tuple[Adjudication, ...]
) -> Adjudication | None:
    return next((entry for entry in adjudications if matches(finding, entry.rule)), None)


@dataclass(frozen=True)
class Score:
    task_id: str
    finding_count: int
    gold_count: int
    matched: tuple[tuple[int, str], ...]
    missed_gold: tuple[str, ...]
    valid_extras: tuple[tuple[int, str], ...]
    false_positives: tuple[tuple[int, str], ...]
    duplicates: tuple[tuple[int, str], ...]
    pending: tuple[int, ...]
    severity_agreement: int

    @property
    def recall(self) -> float | None:
        return len(self.matched) / self.gold_count if self.gold_count else None

    @property
    def adjudicated_precision(self) -> float | None:
        correct = len(self.matched) + len(self.valid_extras)
        total = correct + len(self.false_positives) + len(self.duplicates)
        return correct / total if total else None

    @property
    def noise_count(self) -> int:
        return len(self.false_positives) + len(self.duplicates) + len(self.pending)

    @property
    def clean(self) -> bool | None:
        if self.gold_count:
            return None
        return self.finding_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "review-benchmark/score/1",
            "scorer_version": SCORER_VERSION,
            "task_id": self.task_id,
            "finding_count": self.finding_count,
            "gold_count": self.gold_count,
            "matched": [
                {"finding_index": finding_index, "gold_id": gold_id}
                for finding_index, gold_id in self.matched
            ],
            "missed_gold": list(self.missed_gold),
            "valid_extras": [
                {"finding_index": finding_index, "adjudication_id": adjudication_id}
                for finding_index, adjudication_id in self.valid_extras
            ],
            "false_positives": [
                {"finding_index": finding_index, "adjudication_id": adjudication_id}
                for finding_index, adjudication_id in self.false_positives
            ],
            "duplicates": [
                {"finding_index": finding_index, "gold_id": gold_id}
                for finding_index, gold_id in self.duplicates
            ],
            "pending": list(self.pending),
            "recall": self.recall,
            "adjudicated_precision": self.adjudicated_precision,
            "noise_count": self.noise_count,
            "clean": self.clean,
            "severity_agreement": {
                "numerator": self.severity_agreement,
                "denominator": len(self.matched),
            },
        }


def score_findings(task: Task, findings: tuple[Finding, ...]) -> Score:
    assignments = _maximum_matching(findings, task.gold)
    matched_gold = set(assignments.values())
    matched = tuple(
        sorted(
            (finding_index, task.gold[gold_index].id)
            for finding_index, gold_index in assignments.items()
        )
    )
    severity_agreement = sum(
        1
        for finding_index, gold_index in assignments.items()
        if findings[finding_index].severity == task.gold[gold_index].severity
    )

    valid_extras: list[tuple[int, str]] = []
    false_positives: list[tuple[int, str]] = []
    duplicates: list[tuple[int, str]] = []
    pending: list[int] = []
    for finding_index, finding in enumerate(findings):
        if finding_index in assignments:
            continue
        duplicate = next(
            (
                task.gold[gold_index]
                for gold_index in sorted(matched_gold)
                if matches(finding, task.gold[gold_index].rule)
            ),
            None,
        )
        if duplicate is not None:
            duplicates.append((finding_index, duplicate.id))
            continue
        adjudication = _first_adjudication(finding, task.adjudications)
        if adjudication is None:
            pending.append(finding_index)
        elif adjudication.verdict == "valid_extra":
            valid_extras.append((finding_index, adjudication.id))
        else:
            false_positives.append((finding_index, adjudication.id))

    return Score(
        task_id=task.id,
        finding_count=len(findings),
        gold_count=len(task.gold),
        matched=matched,
        missed_gold=tuple(
            finding.id for index, finding in enumerate(task.gold) if index not in matched_gold
        ),
        valid_extras=tuple(valid_extras),
        false_positives=tuple(false_positives),
        duplicates=tuple(duplicates),
        pending=tuple(pending),
        severity_agreement=severity_agreement,
    )
