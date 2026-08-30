"""Strict, dependency-free loading of benchmark tasks and reviewer findings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

TASK_SCHEMA_V1 = "review-benchmark/task/1"
TASK_SCHEMA_V2 = "review-benchmark/task/2"
# Kept as the task/1 value for callers that imported the original constant.
TASK_SCHEMA = TASK_SCHEMA_V1
TASK_SCHEMAS = (TASK_SCHEMA_V1, TASK_SCHEMA_V2)
GOLD_SCHEMA = "review-benchmark/gold/1"
ADJUDICATION_SCHEMA = "review-benchmark/adjudications/1"
FINDINGS_SCHEMA = "review-benchmark/findings/1"
RELEASE_SCHEMA = "review-benchmark/release/1"
RELEASE_SCHEMA_V2 = "review-benchmark/release/2"

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

_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_VERSION_RE = re.compile(
    r"^(?:[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._+:/@<>=~^,* -]*"
    r"[A-Za-z0-9._+:/@<>=~^,*])$"
)


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


def _require_keys(
    value: dict[str, Any],
    label: str,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise BenchmarkError(f"{label} is missing required properties: {missing}")
    unexpected = sorted(value.keys() - required - optional)
    if unexpected:
        raise BenchmarkError(f"{label} has unexpected properties: {unexpected}")


def _require_identifier(value: object, label: str) -> str:
    identifier = _require_str(value, label)
    if len(identifier) > 80 or _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise BenchmarkError(
            f"{label} must be a normalized lower-case identifier of at most 80 characters"
        )
    return identifier


def _require_identifiers(
    value: object, label: str, *, min_items: int = 0, max_items: int = 64
) -> tuple[str, ...]:
    items = _require_list(value, label)
    if len(items) < min_items:
        raise BenchmarkError(f"{label} must contain at least {min_items} entries")
    if len(items) > max_items:
        raise BenchmarkError(f"{label} must contain at most {max_items} entries")
    identifiers = tuple(
        _require_identifier(item, f"{label}[{index}]")
        for index, item in enumerate(items)
    )
    if len(identifiers) != len(set(identifiers)):
        raise BenchmarkError(f"{label} must not contain duplicate entries")
    return identifiers


def _require_date(value: object, label: str) -> date:
    raw = _require_str(value, label)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise BenchmarkError(f"{label} must be a valid YYYY-MM-DD date") from exc
    if parsed.isoformat() != raw:
        raise BenchmarkError(f"{label} must be a normalized YYYY-MM-DD date")
    return parsed


def _require_version(value: object, label: str) -> str:
    version = _require_str(value, label)
    if len(version) > 128 or _VERSION_RE.fullmatch(version) is None:
        raise BenchmarkError(
            f"{label} must be a normalized version string of at most 128 characters"
        )
    return version


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkError(f"JSON contains duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json_number(value: str) -> None:
    raise BenchmarkError(f"JSON contains a non-finite numeric literal {value!r}")


def _validate_json_unicode(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_json_unicode(key)
            _validate_json_unicode(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json_unicode(child)
    elif isinstance(value, str) and any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise BenchmarkError("JSON contains an unpaired Unicode surrogate")


def _json_loads(raw: str | bytes, label: str) -> object:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json_number,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise BenchmarkError(f"invalid JSON in {label}: {exc}") from exc
    _validate_json_unicode(value)
    return value


def _read_json(path: Path, label: str) -> object:
    if not path.is_file():
        raise BenchmarkError(f"missing {label}: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BenchmarkError(f"cannot read {label} {path}: {exc}") from exc
    return _json_loads(raw, f"{label} {path}")


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
class PrimaryCoverage:
    language: str
    ecosystem: str

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> PrimaryCoverage:
        item = _require_dict(value, label)
        _require_keys(item, label, required={"language", "ecosystem"})
        return cls(
            language=_require_identifier(item.get("language"), f"{label}.language"),
            ecosystem=_require_identifier(item.get("ecosystem"), f"{label}.ecosystem"),
        )


@dataclass(frozen=True)
class DataCoverage:
    layers: tuple[str, ...]
    databases: tuple[str, ...]
    providers: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> DataCoverage:
        item = _require_dict(value, label)
        _require_keys(item, label, required={"layers", "databases", "providers"})
        return cls(
            layers=_require_identifiers(item.get("layers"), f"{label}.layers"),
            databases=_require_identifiers(item.get("databases"), f"{label}.databases"),
            providers=_require_identifiers(item.get("providers"), f"{label}.providers"),
        )


@dataclass(frozen=True)
class CloudCoverage:
    provider: str
    services: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> CloudCoverage:
        item = _require_dict(value, label)
        _require_keys(item, label, required={"provider", "services"})
        return cls(
            provider=_require_identifier(item.get("provider"), f"{label}.provider"),
            services=_require_identifiers(item.get("services"), f"{label}.services"),
        )


@dataclass(frozen=True)
class TaskCoverage:
    primary: PrimaryCoverage
    secondary_languages: tuple[str, ...]
    frameworks: tuple[str, ...]
    libraries: tuple[str, ...]
    data: DataCoverage
    cloud: tuple[CloudCoverage, ...]
    artifacts: tuple[str, ...]
    tracks: tuple[str, ...]
    surfaces: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object, *, label: str = "task.coverage") -> TaskCoverage:
        item = _require_dict(value, label)
        _require_keys(
            item,
            label,
            required={
                "primary",
                "secondary_languages",
                "frameworks",
                "libraries",
                "data",
                "cloud",
                "artifacts",
                "tracks",
                "surfaces",
            },
        )
        cloud_items = _require_list(item.get("cloud"), f"{label}.cloud")
        if len(cloud_items) > 16:
            raise BenchmarkError(f"{label}.cloud must contain at most 16 entries")
        cloud = tuple(
            CloudCoverage.from_dict(entry, label=f"{label}.cloud[{index}]")
            for index, entry in enumerate(cloud_items)
        )
        providers = [entry.provider for entry in cloud]
        if len(providers) != len(set(providers)):
            raise BenchmarkError(f"{label}.cloud must contain each provider at most once")
        primary = PrimaryCoverage.from_dict(item.get("primary"), label=f"{label}.primary")
        secondary_languages = _require_identifiers(
            item.get("secondary_languages"),
            f"{label}.secondary_languages",
            max_items=16,
        )
        if primary.language in secondary_languages:
            raise BenchmarkError(
                f"{label}.secondary_languages must not repeat the primary language"
            )
        return cls(
            primary=primary,
            secondary_languages=secondary_languages,
            frameworks=_require_identifiers(item.get("frameworks"), f"{label}.frameworks"),
            libraries=_require_identifiers(item.get("libraries"), f"{label}.libraries"),
            data=DataCoverage.from_dict(item.get("data"), label=f"{label}.data"),
            cloud=cloud,
            artifacts=_require_identifiers(
                item.get("artifacts"), f"{label}.artifacts", min_items=1
            ),
            tracks=_require_identifiers(
                item.get("tracks"), f"{label}.tracks", min_items=1
            ),
            surfaces=_require_identifiers(item.get("surfaces"), f"{label}.surfaces"),
        )

    def tags(self) -> tuple[str, ...]:
        """Return deterministic, namespaced slice tags; never task weights."""
        tags = {
            f"primary-language:{self.primary.language}",
            f"primary-ecosystem:{self.primary.ecosystem}",
        }
        tags.update(f"secondary-language:{value}" for value in self.secondary_languages)
        tags.update(f"framework:{value}" for value in self.frameworks)
        tags.update(f"library:{value}" for value in self.libraries)
        tags.update(f"data-layer:{value}" for value in self.data.layers)
        tags.update(f"database:{value}" for value in self.data.databases)
        tags.update(f"data-provider:{value}" for value in self.data.providers)
        for cloud in self.cloud:
            tags.add(f"cloud-provider:{cloud.provider}")
            tags.update(
                f"cloud-service:{cloud.provider}/{service}" for service in cloud.services
            )
        tags.update(f"artifact:{value}" for value in self.artifacts)
        tags.update(f"track:{value}" for value in self.tracks)
        tags.update(f"surface:{value}" for value in self.surfaces)
        return tuple(sorted(tags))


@dataclass(frozen=True)
class Lifecycle:
    state: str
    as_of: date

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> Lifecycle:
        item = _require_dict(value, label)
        _require_keys(item, label, required={"state", "as_of"})
        return cls(
            state=_require_identifier(item.get("state"), f"{label}.state"),
            as_of=_require_date(item.get("as_of"), f"{label}.as_of"),
        )


@dataclass(frozen=True)
class VersionLifecycle:
    source: str | None
    target: str | None
    as_of: date

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> VersionLifecycle:
        item = _require_dict(value, label)
        _require_keys(
            item,
            label,
            required={"as_of"},
            optional={"source", "target"},
        )
        source_raw = item.get("source")
        target_raw = item.get("target")
        if source_raw is None and target_raw is None:
            raise BenchmarkError(f"{label} must define source or target state")
        return cls(
            source=(
                None
                if source_raw is None
                else _require_identifier(source_raw, f"{label}.source")
            ),
            target=(
                None
                if target_raw is None
                else _require_identifier(target_raw, f"{label}.target")
            ),
            as_of=_require_date(item.get("as_of"), f"{label}.as_of"),
        )


@dataclass(frozen=True)
class VersionComponent:
    kind: str
    name: str
    source: str
    target: str
    lifecycle: VersionLifecycle | None

    @classmethod
    def from_dict(cls, value: object, *, label: str) -> VersionComponent:
        item = _require_dict(value, label)
        _require_keys(
            item,
            label,
            required={"kind", "name", "source", "target"},
            optional={"lifecycle"},
        )
        lifecycle_raw = item.get("lifecycle")
        return cls(
            kind=_require_identifier(item.get("kind"), f"{label}.kind"),
            name=_require_identifier(item.get("name"), f"{label}.name"),
            source=_require_version(item.get("source"), f"{label}.source"),
            target=_require_version(item.get("target"), f"{label}.target"),
            lifecycle=(
                None
                if lifecycle_raw is None
                else VersionLifecycle.from_dict(lifecycle_raw, label=f"{label}.lifecycle")
            ),
        )


@dataclass(frozen=True)
class VersionContext:
    as_of: date
    components: tuple[VersionComponent, ...]

    @classmethod
    def from_dict(
        cls, value: object, *, label: str = "task.version_context"
    ) -> VersionContext:
        item = _require_dict(value, label)
        _require_keys(item, label, required={"as_of", "components"})
        raw_components = _require_list(item.get("components"), f"{label}.components")
        if not raw_components:
            raise BenchmarkError(f"{label}.components must contain at least 1 entry")
        if len(raw_components) > 64:
            raise BenchmarkError(f"{label}.components must contain at most 64 entries")
        components = tuple(
            VersionComponent.from_dict(entry, label=f"{label}.components[{index}]")
            for index, entry in enumerate(raw_components)
        )
        identities = [(entry.kind, entry.name) for entry in components]
        if len(identities) != len(set(identities)):
            raise BenchmarkError(
                f"{label}.components must contain each kind/name pair at most once"
            )
        return cls(
            as_of=_require_date(item.get("as_of"), f"{label}.as_of"),
            components=components,
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
    schema: str = TASK_SCHEMA_V1
    coverage: TaskCoverage | None = None
    version_context: VersionContext | None = None
    lifecycle: Lifecycle | None = None

    @property
    def coverage_tags(self) -> tuple[str, ...]:
        if self.coverage is None:
            return (f"primary-language:{self.language}",)
        return self.coverage.tags()


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
    task_schema = manifest.get("schema")
    if task_schema not in TASK_SCHEMAS:
        raise BenchmarkError(f"task.schema must be one of {TASK_SCHEMAS}")
    if task_schema == TASK_SCHEMA_V2:
        _require_keys(
            manifest,
            "task",
            required={
                "schema",
                "task_id",
                "title",
                "family_id",
                "origin",
                "visibility",
                "source",
                "files",
                "context",
                "coverage",
                "version_context",
                "lifecycle",
            },
        )
    task_id = _require_str(manifest.get("task_id"), "task.task_id")
    if task_schema == TASK_SCHEMA_V2 and _TASK_ID_RE.fullmatch(task_id) is None:
        raise BenchmarkError("task.task_id must be a normalized task identifier")
    title = _require_str(manifest.get("title"), "task.title")
    family_id = _require_str(manifest.get("family_id"), "task.family_id")
    if task_schema == TASK_SCHEMA_V2:
        if len(title) > 200:
            raise BenchmarkError("task.title must contain at most 200 characters")
        if len(family_id) > 80:
            raise BenchmarkError("task.family_id must contain at most 80 characters")
    origin = _require_str(manifest.get("origin"), "task.origin")
    if origin not in ORIGINS:
        raise BenchmarkError(f"task.origin must be one of {ORIGINS}")
    visibility = _require_str(manifest.get("visibility"), "task.visibility")
    if visibility not in {"public", "private"}:
        raise BenchmarkError("task.visibility must be 'public' or 'private'")
    files = _require_dict(manifest.get("files"), "task.files")
    if task_schema == TASK_SCHEMA_V2:
        _require_keys(
            files,
            "task.files",
            required={"diff", "checkout", "gold"},
            optional={"adjudications"},
        )
        _require_dict(manifest.get("source"), "task.source")
        _require_dict(manifest.get("context"), "task.context")
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

    coverage: TaskCoverage | None = None
    version_context: VersionContext | None = None
    lifecycle: Lifecycle | None = None
    if task_schema == TASK_SCHEMA_V2:
        coverage = TaskCoverage.from_dict(manifest.get("coverage"))
        version_context = VersionContext.from_dict(manifest.get("version_context"))
        lifecycle = Lifecycle.from_dict(manifest.get("lifecycle"), label="task.lifecycle")
        language = coverage.primary.language
    else:
        language = _require_str(manifest.get("language"), "task.language")

    return Task(
        root=root,
        id=task_id,
        title=title,
        family_id=family_id,
        origin=origin,
        language=language,
        visibility=visibility,
        diff_path=diff_path,
        checkout_path=checkout_path,
        gold=gold,
        adjudications=adjudications,
        manifest=manifest,
        schema=task_schema,
        coverage=coverage,
        version_context=version_context,
        lifecycle=lifecycle,
    )
