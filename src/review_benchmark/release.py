"""Strict release inventory validation and public-safe coverage summaries."""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from review_benchmark.models import (
    RELEASE_SCHEMA,
    RELEASE_SCHEMA_V2,
    BenchmarkError,
    Task,
    _json_loads,
    _require_dict,
    _require_keys,
    _require_list,
    _require_str,
    load_task,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPARSE_POINT = 0x400
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None and isjunction(path):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise BenchmarkError(f"cannot inspect release path {path}: {exc}") from exc
    return bool(attributes & _REPARSE_POINT)


def _normalized_release_path(value: object, label: str) -> str:
    raw = _require_str(value, label)
    if len(raw) > 4096:
        raise BenchmarkError(f"{label} must contain at most 4096 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise BenchmarkError(f"{label} must not contain control characters")
    if "\\" in raw:
        raise BenchmarkError(f"{label} must use forward slashes")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or "." in path.parts
        or path.as_posix() != raw
        or ":" in path.parts[0]
    ):
        raise BenchmarkError(f"{label} must be a normalized release-relative path")
    return raw


def _scan_release(root: Path) -> dict[str, tuple[int, str]]:
    """Return exact file inventory without traversing links or reparse points."""

    if not root.is_dir():
        raise BenchmarkError(f"release root is not a directory: {root}")
    if _is_reparse(root):
        raise BenchmarkError("release root must not be a link or reparse point")
    files: dict[str, tuple[int, str]] = {}
    case_names: dict[str, str] = {}

    def visit(directory: Path, prefix: PurePosixPath | None = None) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise BenchmarkError(f"cannot enumerate release directory {directory}: {exc}") from exc
        for entry in entries:
            relative = (
                PurePosixPath(entry.name) if prefix is None else prefix / entry.name
            ).as_posix()
            folded = relative.casefold()
            existing = case_names.get(folded)
            if existing is not None and existing != relative:
                raise BenchmarkError(
                    f"release contains a case-colliding path: {existing!r} and {relative!r}"
                )
            case_names[folded] = relative
            path = Path(entry.path)
            if entry.is_symlink() or _is_reparse(path):
                raise BenchmarkError(f"release contains a link or reparse point: {relative}")
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise BenchmarkError(f"cannot inspect release entry {relative}: {exc}") from exc
            if stat.S_ISDIR(metadata.st_mode):
                visit(path, PurePosixPath(relative))
            elif stat.S_ISREG(metadata.st_mode):
                if relative != "MANIFEST.json":
                    files[relative] = (metadata.st_size, sha256_file(path))
            else:
                raise BenchmarkError(f"release contains a non-regular entry: {relative}")

    visit(root)
    return files


@dataclass(frozen=True)
class Release:
    root: Path
    id: str
    visibility: str
    status: str
    public_benchmark_revision: str | None
    tasks: tuple[Task, ...]
    manifest: dict[str, object]
    manifest_sha256: str


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


def _load_tasks(root: Path, entries_value: object, visibility: str) -> tuple[Task, ...]:
    entries = _require_list(entries_value, "release.tasks")
    if not entries:
        raise BenchmarkError("release.tasks must not be empty")
    if len(entries) > 100_000:
        raise BenchmarkError("release.tasks must contain at most 100000 entries")
    tasks: list[Task] = []
    seen_ids: set[str] = set()
    previous_path: str | None = None
    for index, raw in enumerate(entries):
        label = f"release.tasks[{index}]"
        entry = _require_dict(raw, label)
        _require_keys(
            entry,
            label,
            required={"path", "task_id", "task_manifest_sha256"},
        )
        relative = _normalized_release_path(entry.get("path"), f"{label}.path")
        if previous_path is not None and relative <= previous_path:
            raise BenchmarkError("release.tasks must be unique and sorted by path")
        previous_path = relative
        task = load_task(root.joinpath(*PurePosixPath(relative).parts))
        if task.id != entry.get("task_id"):
            raise BenchmarkError(f"release task id mismatch for {relative}")
        if task.id in seen_ids:
            raise BenchmarkError(f"duplicate release task id: {task.id}")
        if task.visibility != visibility:
            raise BenchmarkError(f"task {task.id} visibility differs from release")
        expected = entry.get("task_manifest_sha256")
        if not isinstance(expected, str) or _SHA256_RE.fullmatch(expected) is None:
            raise BenchmarkError(f"{label}.task_manifest_sha256 must be a SHA-256 digest")
        actual = sha256_file(task.root / "task.json")
        if expected != actual:
            raise BenchmarkError(f"task manifest digest mismatch for {task.id}")
        seen_ids.add(task.id)
        tasks.append(task)
    return tuple(tasks)


def _validate_artifacts(value: object, actual_files: dict[str, tuple[int, str]]) -> None:
    artifacts = _require_list(value, "release.artifacts")
    if not artifacts:
        raise BenchmarkError("release.artifacts must not be empty")
    if len(artifacts) > 1_000_000:
        raise BenchmarkError("release.artifacts must contain at most 1000000 entries")
    expected: dict[str, tuple[int, str]] = {}
    case_names: dict[str, str] = {}
    previous_path: str | None = None
    for index, raw in enumerate(artifacts):
        label = f"release.artifacts[{index}]"
        item = _require_dict(raw, label)
        _require_keys(item, label, required={"path", "size_bytes", "sha256"})
        relative = _normalized_release_path(item.get("path"), f"{label}.path")
        if relative == "MANIFEST.json":
            raise BenchmarkError("release.artifacts must not include MANIFEST.json")
        if previous_path is not None and relative <= previous_path:
            raise BenchmarkError("release.artifacts must be unique and sorted by path")
        previous_path = relative
        folded = relative.casefold()
        if folded in case_names:
            raise BenchmarkError("release.artifacts contain a case-colliding path")
        case_names[folded] = relative
        size = item.get("size_bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, (int, float))
            or not math.isfinite(float(size))
            or not float(size).is_integer()
            or float(size) < 0
            or float(size) > _MAX_SAFE_INTEGER
        ):
            raise BenchmarkError(
                f"{label}.size_bytes must be an integer between 0 and "
                f"{_MAX_SAFE_INTEGER}"
            )
        size = int(size)
        item["size_bytes"] = size
        digest = item.get("sha256")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise BenchmarkError(f"{label}.sha256 must be a lowercase SHA-256 digest")
        expected[relative] = (size, digest)
    if expected.keys() != actual_files.keys():
        missing = sorted(actual_files.keys() - expected.keys())
        extra = sorted(expected.keys() - actual_files.keys())
        raise BenchmarkError(
            f"release artifact inventory is not exact: unmanifested={missing}, missing={extra}"
        )
    for relative, declared in expected.items():
        if declared != actual_files[relative]:
            raise BenchmarkError(f"release artifact size or digest mismatch for {relative}")


def _load_legacy_release(
    root: Path, manifest: dict[str, object], manifest_sha256: str
) -> Release:
    """Preserve the published release/1 loader's permissive extension behavior."""

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
        if entry.get("task_manifest_sha256") != sha256_file(task.root / "task.json"):
            raise BenchmarkError(f"task manifest digest mismatch for {task.id}")
        seen_ids.add(task.id)
        tasks.append(task)
    status = manifest.get("status")
    public_revision = manifest.get("public_benchmark_revision")
    return Release(
        root=root,
        id=release_id,
        visibility=visibility,
        status=status if isinstance(status, str) else "",
        public_benchmark_revision=(
            public_revision if isinstance(public_revision, str) else None
        ),
        tasks=tuple(tasks),
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )


def load_release(root: Path, *, require_official_contract: bool = False) -> Release:
    supplied_root = Path(root).absolute()
    manifest_path = supplied_root / "MANIFEST.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise BenchmarkError(f"cannot read release manifest {manifest_path}: {exc}") from exc
    manifest = _require_dict(
        _json_loads(manifest_bytes, f"release manifest {manifest_path}"), "release"
    )
    schema = manifest.get("schema")
    if schema == RELEASE_SCHEMA:
        if require_official_contract:
            raise BenchmarkError("authoritative release loading requires release/2")
        return _load_legacy_release(
            supplied_root.resolve(),
            manifest,
            hashlib.sha256(manifest_bytes).hexdigest(),
        )
    if schema != RELEASE_SCHEMA_V2:
        raise BenchmarkError(
            f"release.schema must be one of {(RELEASE_SCHEMA, RELEASE_SCHEMA_V2)}"
        )
    actual_files = _scan_release(supplied_root)
    root = supplied_root.resolve()
    _require_keys(
        manifest,
        "release",
        required={
            "schema",
            "release_id",
            "visibility",
            "status",
            "public_benchmark_revision",
            "tasks",
            "artifacts",
        },
    )
    status = _require_str(manifest.get("status"), "release.status")
    if status != "official":
        raise BenchmarkError("release/2 status must be 'official'")
    public_revision = _require_str(
        manifest.get("public_benchmark_revision"),
        "release.public_benchmark_revision",
    )
    if _GIT_SHA_RE.fullmatch(public_revision) is None:
        raise BenchmarkError(
            "release.public_benchmark_revision must be a lowercase 40-character Git SHA"
        )
    _validate_artifacts(manifest.get("artifacts"), actual_files)
    release_id = _require_str(manifest.get("release_id"), "release.release_id")
    if len(release_id) > 200:
        raise BenchmarkError("release.release_id must contain at most 200 characters")
    visibility = _require_str(manifest.get("visibility"), "release.visibility")
    if visibility not in {"public", "private"}:
        raise BenchmarkError("release.visibility must be public or private")
    tasks = _load_tasks(root, manifest.get("tasks"), visibility)
    if _scan_release(root) != actual_files:
        raise BenchmarkError("release artifacts changed while validation was in progress")
    return Release(
        root=root,
        id=release_id,
        visibility=visibility,
        status=status,
        public_benchmark_revision=public_revision,
        tasks=tasks,
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
