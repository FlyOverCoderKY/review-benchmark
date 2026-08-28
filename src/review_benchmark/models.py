"""Strict, dependency-free loading of benchmark tasks and reviewer findings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

TASK_SCHEMA = "review-benchmark/task/1"
GOLD_SCHEMA = "review-benchmark/gold/1"
ADJUDICATION_SCHEMA = "review-benchmark/adjudications/1"
FINDINGS_SCHEMA = "review-benchmark/findings/1"
RELEASE_SCHEMA = "review-benchmark/release/1"

SEVERITIES = ("bug", "risk", "nit")
CONTEXT_CLASSES = ("diff", "file", "repo", "history", "external-authority")
ORIGINS = (
    "planted",
    "clean-control",
    "human-review",
    "production-escape",
    "fresh-mutation",
    "partner-unpublished",
)
ADJUDICATION_VERDICTS = ("valid_extra", "false_positive")


class BenchmarkError(ValueError):
    """Raised when a benchmark artifact violates its public contract."""


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{label} must be a JSON object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BenchmarkError(f"{label} must be a JSON array")
    return value


def _require_str(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise BenchmarkError(f"{label} must be a non-empty string")
    return value


def _read_json(path: Path, label: str) -> object:
    if not path.is_file():
        raise BenchmarkError(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid JSON in {label} {path}: {exc}") from exc


def normalize_relative_path(value: object, label: str) -> str:
    raw = _require_str(value, label).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or raw.startswith("./"):
        raise BenchmarkError(f"{label} must be a normalized task-relative path")
    return path.as_posix()


def confined(root: Path, relative: str, label: str) -> Path:
    base = root.resolve()
    resolved = (base / relative).resolve()
    if resolved != base and base not in resolved.parents:
        raise BenchmarkError(f"{label} escapes task directory: {relative!r}")
    return resolved


@dataclass(frozen=True)
class Finding:
    path: str | None
    line: int | None
    severity: str
    title: str
    detail: str

    @classmethod
    def from_dict(cls, value: object, *, label: str = "finding") -> Finding:
        item = _require_dict(value, label)
        raw_path = item.get("path")
        path = None if raw_path is None else normalize_relative_path(raw_path, f"{label}.path")
        line = item.get("line")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            raise BenchmarkError(f"{label}.line must be a positive integer or null")
        severity = _require_str(item.get("severity"), f"{label}.severity")
        if severity not in SEVERITIES:
            raise BenchmarkError(f"{label}.severity must be one of {SEVERITIES}")
        return cls(
            path=path,
            line=line,
            severity=severity,
            title=_require_str(item.get("title"), f"{label}.title"),
            detail=_require_str(item.get("detail"), f"{label}.detail"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MatchRule:
    paths: tuple[str, ...]
    keywords: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> MatchRule:
        item = _require_dict(value, label)
        paths = tuple(
            normalize_relative_path(path, f"{label}.paths")
            for path in _require_list(item.get("paths", []), f"{label}.paths")
        )
        raw_keywords = _require_list(item.get("keywords"), f"{label}.keywords")
        if not raw_keywords:
            raise BenchmarkError(f"{label}.keywords must not be empty")
        keywords: list[str] = []
        for index, raw in enumerate(raw_keywords):
            pattern = _require_str(raw, f"{label}.keywords[{index}]")
            try:
                re.compile(pattern, flags=re.IGNORECASE | re.DOTALL)
            except re.error as exc:
                raise BenchmarkError(f"invalid regex in {label}.keywords[{index}]: {exc}") from exc
            keywords.append(pattern)
        return cls(paths=paths, keywords=tuple(keywords))


@dataclass(frozen=True)
class GoldFinding:
    id: str
    title: str
    severity: str
    context: str
    defect_statement: str
    trigger: str
    impact: str
    proof: tuple[str, ...]
    rule: MatchRule

    @classmethod
    def from_dict(cls, value: object, *, index: int) -> GoldFinding:
        label = f"gold.findings[{index}]"
        item = _require_dict(value, label)
        severity = _require_str(item.get("severity"), f"{label}.severity")
        if severity not in SEVERITIES:
            raise BenchmarkError(f"{label}.severity must be one of {SEVERITIES}")
        context = _require_str(item.get("context"), f"{label}.context")
        if context not in CONTEXT_CLASSES:
            raise BenchmarkError(f"{label}.context must be one of {CONTEXT_CLASSES}")
        proof = tuple(
            _require_str(entry, f"{label}.proof[{proof_index}]")
            for proof_index, entry in enumerate(
                _require_list(item.get("proof"), f"{label}.proof")
            )
        )
        if not proof:
            raise BenchmarkError(f"{label}.proof must not be empty")
        return cls(
            id=_require_str(item.get("id"), f"{label}.id"),
            title=_require_str(item.get("title"), f"{label}.title"),
            severity=severity,
            context=context,
            defect_statement=_require_str(
                item.get("defect_statement"), f"{label}.defect_statement"
            ),
            trigger=_require_str(item.get("trigger"), f"{label}.trigger"),
            impact=_require_str(item.get("impact"), f"{label}.impact"),
            proof=proof,
            rule=MatchRule.from_dict(item.get("match"), label=f"{label}.match"),
        )


@dataclass(frozen=True)
class Adjudication:
    id: str
    verdict: str
    rationale: str
    rule: MatchRule

    @classmethod
    def from_dict(cls, value: object, *, index: int) -> Adjudication:
        label = f"adjudications.findings[{index}]"
        item = _require_dict(value, label)
        verdict = _require_str(item.get("verdict"), f"{label}.verdict")
        if verdict not in ADJUDICATION_VERDICTS:
            raise BenchmarkError(f"{label}.verdict must be one of {ADJUDICATION_VERDICTS}")
        return cls(
            id=_require_str(item.get("id"), f"{label}.id"),
            verdict=verdict,
            rationale=_require_str(item.get("rationale"), f"{label}.rationale"),
            rule=MatchRule.from_dict(item.get("match"), label=f"{label}.match"),
        )


@dataclass(frozen=True)
class Task:
    root: Path
    id: str
    title: str
    family_id: str
    origin: str
    language: str
    visibility: str
    diff_path: Path
    checkout_path: Path
    gold: tuple[GoldFinding, ...]
    adjudications: tuple[Adjudication, ...]
    manifest: dict[str, Any]


def load_findings(path: Path, *, expected_task_id: str | None = None) -> tuple[Finding, ...]:
    payload = _require_dict(_read_json(path, "findings"), "findings")
    if payload.get("schema") != FINDINGS_SCHEMA:
        raise BenchmarkError(f"findings.schema must be {FINDINGS_SCHEMA!r}")
    task_id = _require_str(payload.get("task_id"), "findings.task_id")
    if expected_task_id is not None and task_id != expected_task_id:
        raise BenchmarkError(
            f"findings task_id {task_id!r} does not match task {expected_task_id!r}"
        )
    findings = tuple(
        Finding.from_dict(value, label=f"findings.findings[{index}]")
        for index, value in enumerate(
            _require_list(payload.get("findings"), "findings.findings")
        )
    )
    return findings


def load_task(root: Path) -> Task:
    root = root.resolve()
    manifest = _require_dict(_read_json(root / "task.json", "task manifest"), "task")
    if manifest.get("schema") != TASK_SCHEMA:
        raise BenchmarkError(f"task.schema must be {TASK_SCHEMA!r}")
    task_id = _require_str(manifest.get("task_id"), "task.task_id")
    origin = _require_str(manifest.get("origin"), "task.origin")
    if origin not in ORIGINS:
        raise BenchmarkError(f"task.origin must be one of {ORIGINS}")
    visibility = _require_str(manifest.get("visibility"), "task.visibility")
    if visibility not in {"public", "private"}:
        raise BenchmarkError("task.visibility must be 'public' or 'private'")
    files = _require_dict(manifest.get("files"), "task.files")
    diff_rel = normalize_relative_path(files.get("diff"), "task.files.diff")
    checkout_rel = normalize_relative_path(files.get("checkout"), "task.files.checkout")
    gold_rel = normalize_relative_path(files.get("gold"), "task.files.gold")
    adjudications_rel = files.get("adjudications")
    diff_path = confined(root, diff_rel, "task.files.diff")
    checkout_path = confined(root, checkout_rel, "task.files.checkout")
    gold_path = confined(root, gold_rel, "task.files.gold")
    if not diff_path.is_file():
        raise BenchmarkError(f"task diff does not exist: {diff_path}")
    if not checkout_path.is_dir():
        raise BenchmarkError(f"task checkout does not exist: {checkout_path}")

    gold_payload = _require_dict(_read_json(gold_path, "gold file"), "gold")
    if gold_payload.get("schema") != GOLD_SCHEMA:
        raise BenchmarkError(f"gold.schema must be {GOLD_SCHEMA!r}")
    if gold_payload.get("task_id") != task_id:
        raise BenchmarkError("gold.task_id must match task.task_id")
    gold = tuple(
        GoldFinding.from_dict(value, index=index)
        for index, value in enumerate(
            _require_list(gold_payload.get("findings"), "gold.findings")
        )
    )
    gold_ids = [finding.id for finding in gold]
    if len(gold_ids) != len(set(gold_ids)):
        raise BenchmarkError("gold finding ids must be unique")

    adjudications: tuple[Adjudication, ...] = ()
    if adjudications_rel is not None:
        rel = normalize_relative_path(adjudications_rel, "task.files.adjudications")
        payload = _require_dict(
            _read_json(confined(root, rel, "task.files.adjudications"), "adjudications"),
            "adjudications",
        )
        if payload.get("schema") != ADJUDICATION_SCHEMA:
            raise BenchmarkError(
                f"adjudications.schema must be {ADJUDICATION_SCHEMA!r}"
            )
        if payload.get("task_id") != task_id:
            raise BenchmarkError("adjudications.task_id must match task.task_id")
        adjudications = tuple(
            Adjudication.from_dict(value, index=index)
            for index, value in enumerate(
                _require_list(payload.get("findings"), "adjudications.findings")
            )
        )
        ids = [entry.id for entry in adjudications]
        if len(ids) != len(set(ids)):
            raise BenchmarkError("adjudication ids must be unique")

    return Task(
        root=root,
        id=task_id,
        title=_require_str(manifest.get("title"), "task.title"),
        family_id=_require_str(manifest.get("family_id"), "task.family_id"),
        origin=origin,
        language=_require_str(manifest.get("language"), "task.language"),
        visibility=visibility,
        diff_path=diff_path,
        checkout_path=checkout_path,
        gold=gold,
        adjudications=adjudications,
        manifest=manifest,
    )
