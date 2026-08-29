"""Release validation and public-safe aggregate scoring."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from review_benchmark.models import (
    RELEASE_SCHEMA,
    BenchmarkError,
    Task,
    _read_json,
    _require_dict,
    _require_list,
    _require_str,
    load_task,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Release:
    root: Path
    id: str
    visibility: str
    tasks: tuple[Task, ...]
    manifest: dict[str, object]


@dataclass(frozen=True)
class CoverageSummary:
    """Coverage membership without changing the one-task/one-weight invariant."""

    task_ids: tuple[str, ...]
    slice_counts: tuple[tuple[str, int], ...]

    @property
    def task_count(self) -> int:
        return len(self.task_ids)


def summarize_task_coverage(tasks: tuple[Task, ...]) -> CoverageSummary:
    """Count overlapping slices while retaining one unique headline task count."""

    task_ids: set[str] = set()
    slice_members: dict[str, set[str]] = {}
    for task in tasks:
        if task.id in task_ids:
            raise BenchmarkError(f"duplicate task id in coverage summary: {task.id}")
        task_ids.add(task.id)
        for tag in task.coverage_tags:
            slice_members.setdefault(tag, set()).add(task.id)
    return CoverageSummary(
        task_ids=tuple(sorted(task_ids)),
        slice_counts=tuple(
            (tag, len(members)) for tag, members in sorted(slice_members.items())
        ),
    )


def load_release(root: Path) -> Release:
    root = root.resolve()
    manifest = _require_dict(_read_json(root / "MANIFEST.json", "release manifest"), "release")
    if manifest.get("schema") != RELEASE_SCHEMA:
        raise BenchmarkError(f"release.schema must be {RELEASE_SCHEMA!r}")
    release_id = _require_str(manifest.get("release_id"), "release.release_id")
    visibility = _require_str(manifest.get("visibility"), "release.visibility")
    if visibility not in {"public", "private"}:
        raise BenchmarkError("release.visibility must be public or private")
    entries = _require_list(manifest.get("tasks"), "release.tasks")
    if not entries:
        raise BenchmarkError("release.tasks must not be empty")
    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(entries):
        entry = _require_dict(raw, f"release.tasks[{index}]")
        relative = _require_str(entry.get("path"), f"release.tasks[{index}].path")
        if relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
            raise BenchmarkError(f"release.tasks[{index}].path must stay inside release")
        task = load_task(root / relative)
        if task.id != entry.get("task_id"):
            raise BenchmarkError(f"release task id mismatch for {relative}")
        if task.id in seen_ids:
            raise BenchmarkError(f"duplicate release task id: {task.id}")
        if task.visibility != visibility:
            raise BenchmarkError(f"task {task.id} visibility differs from release")
        expected = entry.get("task_manifest_sha256")
        actual = sha256_file(task.root / "task.json")
        if expected != actual:
            raise BenchmarkError(f"task manifest digest mismatch for {task.id}")
        seen_ids.add(task.id)
        tasks.append(task)
    return Release(
        root=root,
        id=release_id,
        visibility=visibility,
        tasks=tuple(tasks),
        manifest=manifest,
    )
