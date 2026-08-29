from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from review_benchmark.models import (
    TASK_SCHEMA_V1,
    TASK_SCHEMA_V2,
    BenchmarkError,
    load_task,
)
from review_benchmark.release import load_release, sha256_file, summarize_task_coverage

ROOT = Path(__file__).parents[1]
V1_SCHEMA_PATH = ROOT / "schemas" / "task.schema.json"
V2_SCHEMA_PATH = ROOT / "schemas" / "task-v2.schema.json"
V2_FIXTURE = ROOT / "fixtures" / "conformance" / "task-v2"


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _validator(path: Path) -> Draft202012Validator:
    schema = _read_json(path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _copy_v2_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "task-v2"
    shutil.copytree(V2_FIXTURE, destination)
    return destination


def _write_manifest(root: Path, payload: dict[str, object]) -> None:
    (root / "task.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def test_all_published_json_schemas_are_valid_draft_2020_12() -> None:
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        schema = _read_json(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_published_task_v1_fixtures_remain_valid_and_loadable() -> None:
    validator = _validator(V1_SCHEMA_PATH)
    manifests = sorted((ROOT / "fixtures").glob("public-v*/tasks/*/task.json"))
    assert manifests
    for manifest_path in manifests:
        manifest = _read_json(manifest_path)
        validator.validate(manifest)
        task = load_task(manifest_path.parent)
        assert task.schema == TASK_SCHEMA_V1
        assert task.coverage is None


def test_public_v2_conformance_fixture_matches_schema_and_typed_model() -> None:
    manifest = _read_json(V2_FIXTURE / "task.json")
    _validator(V2_SCHEMA_PATH).validate(manifest)

    task = load_task(V2_FIXTURE)

    assert task.schema == TASK_SCHEMA_V2
    assert task.language == "csharp"
    assert task.coverage is not None
    assert task.coverage.primary.ecosystem == "dotnet"
    assert task.coverage.secondary_languages == ("bicep", "tsql", "yaml")
    assert task.coverage.data.databases == ("sql-server",)
    assert task.coverage.cloud[0].provider == "azure"
    assert task.coverage.cloud[0].services == ("app-service", "azure-sql")
    assert task.version_context is not None
    versions = {
        (component.kind, component.name): (component.source, component.target)
        for component in task.version_context.components
    }
    assert versions[("runtime", "dotnet")] == ("8.0.11", "9.0.2")
    assert versions[("iac-provider", "azure-resource-manager")] == (
        "0.31.92",
        "0.33.93",
    )
    assert versions[("lockfile", "packages-lock-json")] == ("1", "1")
    assert task.lifecycle is not None
    assert task.lifecycle.as_of.isoformat() == "2025-03-01"


def test_task_v2_schema_rejects_non_normalized_technology_values() -> None:
    manifest = _read_json(V2_FIXTURE / "task.json")
    coverage = manifest["coverage"]
    assert isinstance(coverage, dict)
    coverage["frameworks"] = ["ASP.NET Core"]

    with pytest.raises(ValidationError):
        _validator(V2_SCHEMA_PATH).validate(manifest)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda manifest: manifest.__setitem__("unknown", True), "unexpected properties"),
        (
            lambda manifest: manifest["coverage"].__setitem__(
                "frameworks", ["ASP.NET-Core"]
            ),
            "normalized lower-case identifier",
        ),
        (
            lambda manifest: manifest["coverage"].__setitem__(
                "cloud",
                [
                    {"provider": "azure", "services": ["app-service"]},
                    {"provider": "azure", "services": ["azure-sql"]},
                ],
            ),
            "each provider at most once",
        ),
        (
            lambda manifest: manifest["version_context"]["components"].append(
                {
                    "kind": "runtime",
                    "name": "dotnet",
                    "source": "8.0.11",
                    "target": "9.0.2",
                }
            ),
            "each kind/name pair at most once",
        ),
    ],
)
def test_task_v2_loader_enforces_deterministic_contract(
    tmp_path: Path, mutate: object, message: str
) -> None:
    task_root = _copy_v2_fixture(tmp_path)
    manifest = _read_json(task_root / "task.json")
    assert callable(mutate)
    mutate(manifest)
    _write_manifest(task_root, manifest)

    with pytest.raises(BenchmarkError, match=message):
        load_task(task_root)


def test_release_loader_accepts_task_v2_without_rewriting_task_v1(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    task_root = release_root / "tasks" / "task-v2"
    shutil.copytree(V2_FIXTURE, task_root)
    manifest = {
        "schema": "review-benchmark/release/1",
        "release_id": "v2-conformance-release",
        "status": "calibration",
        "visibility": "public",
        "tasks": [
            {
                "task_id": "task-v2-metadata-conformance",
                "path": "tasks/task-v2",
                "task_manifest_sha256": sha256_file(task_root / "task.json"),
            }
        ],
    }
    (release_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    release = load_release(release_root)

    assert release.tasks[0].schema == TASK_SCHEMA_V2


def test_overlapping_coverage_tags_never_multiply_task_macro_weight() -> None:
    task = load_task(V2_FIXTURE)

    summary = summarize_task_coverage((task,))

    assert summary.task_count == 1
    assert len(summary.slice_counts) > summary.task_count
    assert all(count == 1 for _, count in summary.slice_counts)
    assert sum(count for _, count in summary.slice_counts) > summary.task_count


def test_coverage_summary_rejects_duplicate_task_ids() -> None:
    task = load_task(V2_FIXTURE)

    with pytest.raises(BenchmarkError, match="duplicate task id"):
        summarize_task_coverage((task, task))
