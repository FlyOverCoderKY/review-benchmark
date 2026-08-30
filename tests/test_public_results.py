from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from review_benchmark.models import BenchmarkError, _json_loads
from review_benchmark.public_results import (
    evaluation_config_sha256,
    load_public_result,
    load_result_registry,
    validate_registry_against_git_base,
)

ROOT = Path(__file__).parents[1]


def _result(
    record_id: str = "record-1",
    *,
    status: str = "official",
    run_id: str = "run-1",
) -> dict[str, object]:
    payload = {
        "schema": "review-benchmark/public-result/2",
        "record_id": record_id,
        "run_id": run_id,
        "status": status,
        "track": "end-to-end-product",
        "subject": {
            "adapter": "openrouter",
            "label": "OpenRouter Review Bot",
            "model": "z-ai/glm-5.3-flash",
            "provider": "together",
            "expected_reported_provider": "Together",
            "effort": None,
            "fallbacks_disabled": True,
        },
        "release": {
            "id": "private-v1",
            "visibility": "private",
            "task_count": 1,
            "attempts_per_task": 3,
        },
        "provenance": {
            "runner_git_sha": "1" * 40,
            "scorer_git_sha": "2" * 40,
            "public_benchmark_git_sha": "2" * 40,
            "release_git_sha": "3" * 40,
            "product_git_sha": "4" * 40,
            "config_sha256": hashlib.sha256(
                f"raw-run-config:{run_id}".encode()
            ).hexdigest(),
            "evaluation_config_sha256": "0" * 64,
            "release_manifest_sha256": "6" * 64,
            "scorer_version": "review-benchmark-2",
            "provider_policy": "Pinned route; fallbacks disabled.",
        },
        "quality": {
            "attempts_scored": 3,
            "macro_recall": 2 / 3,
            "macro_adjudicated_precision": 1.0,
            "clean_pass_rate": None,
            "mean_noise_count": 0.0,
            "severity_agreement": 1.0,
            "gold_findings": 6,
            "matched_findings": 4,
            "missed_findings": 2,
            "valid_extra_findings": 0,
            "false_positive_findings": 0,
            "duplicate_findings": 0,
            "pending_findings": 0,
            "clean_reviews": 0,
            "clean_reviews_passed": 0,
            "severity_recall": {
                "bug": {"matched": 2, "total": 3, "recall": 2 / 3},
                "risk": {"matched": 2, "total": 3, "recall": 2 / 3},
                "nit": {"matched": 0, "total": 0, "recall": None},
            },
            "attempt_detection_frequency": {
                "mean": 2 / 3,
                "minimum": 1 / 3,
                "maximum": 1.0,
                "gold_findings": 2,
                "detected_every_attempt": 1,
                "detected_some_attempts": 1,
                "never_detected": 0,
            },
        },
        "operations": {
            "reviews_attempted": 3,
            "reviews_with_telemetry": 3,
            "median_elapsed_ms": 1000,
            "total_elapsed_ms": 3000,
            "known_elapsed_ms": 3000,
            "mean_input_tokens": 100,
            "total_input_tokens": 300,
            "mean_output_tokens": 20,
            "total_output_tokens": 60,
            "total_cached_tokens": 0,
            "mean_cost_usd": 0.01,
            "total_cost_usd": 0.03,
            "known_cost_usd": 0.03,
            "costs_reported": 3,
            "providers": ["Together"],
            "attempt_failures": 0,
            "attempts_skipped": 0,
            "cost_guard_triggered": False,
            "observed_cost_usd": 0.03,
        },
    }
    payload["provenance"]["evaluation_config_sha256"] = evaluation_config_sha256(
        payload
    )
    return payload


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _registry(
    root: Path,
    records: list[tuple[dict[str, object], str | None, str | None]],
) -> Path:
    entries = []
    for payload, supersedes, reproduces in records:
        record_id = payload["record_id"]
        path = _write(root / "records" / f"{record_id}.json", payload)
        entries.append(
            {
                "record_id": record_id,
                "path": f"records/{record_id}.json",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "supersedes": supersedes,
                "reproduces": reproduces,
            }
        )
    entries.sort(key=lambda item: item["record_id"])
    return _write(
        root / "registry.json",
        {"schema": "review-benchmark/result-registry/1", "records": entries},
    )


def test_public_result_schema_and_typed_validator_accept_exact_contract(tmp_path: Path) -> None:
    payload = _result()
    schema = _json_loads(
        (ROOT / "schemas" / "public-result-v2.schema.json").read_text(),
        "public result v2 schema",
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    loaded = load_public_result(_write(tmp_path / "result.json", payload))
    assert loaded.record_id == "record-1"
    assert loaded.run_id == "run-1"


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p.__setitem__("extra", True), "unexpected"),
        (
            lambda p: p["provenance"].__setitem__(
                "evaluation_config_sha256", "9" * 64
            ),
            "stable evaluation identity",
        ),
        (lambda p: p["subject"].__setitem__("provider", None), "provider identity"),
        (
            lambda p: p["subject"].__setitem__("fallbacks_disabled", False),
            "fallbacks disabled",
        ),
        (
            lambda p: p["operations"].__setitem__("providers", ["Other"]),
            "observed provider",
        ),
        (
            lambda p: p["quality"].__setitem__("missed_findings", 3),
            r"matched \+ missed",
        ),
        (
            lambda p: p["quality"]["severity_recall"]["bug"].__setitem__("recall", 1),
            "numerator",
        ),
        (
            lambda p: p["quality"]["attempt_detection_frequency"].__setitem__(
                "gold_findings", 3
            ),
            "sum",
        ),
        (
            lambda p: p["operations"].__setitem__("total_cost_usd", None),
            "complete cost",
        ),
        (
            lambda p: p["operations"].__setitem__("observed_cost_usd", float("nan")),
            "finite",
        ),
        (
            lambda p: p["operations"].__setitem__("mean_cost_usd", 0.02),
            "total and denominator",
        ),
        (
            lambda p: p["operations"].__setitem__("total_input_tokens", 300.5),
            "integer",
        ),
        (
            lambda p: p["operations"].__setitem__(
                "total_input_tokens", 9_007_199_254_740_992
            ),
            "integer between",
        ),
    ],
)
def test_public_result_rejects_hostile_or_inconsistent_values(
    tmp_path: Path, mutation, match: str
) -> None:
    payload = _result()
    mutation(payload)
    if match in {"provider identity", "fallbacks disabled"}:
        payload["provenance"]["evaluation_config_sha256"] = evaluation_config_sha256(
            payload
        )
    with pytest.raises(BenchmarkError, match=match):
        load_public_result(_write(tmp_path / "result.json", payload))


def test_registry_loads_reproduction_and_immutable_disposition(tmp_path: Path) -> None:
    first = _result("record-1")
    second = _result("record-2", status="reproduced", run_id="run-2")
    assert first["provenance"]["config_sha256"] != second["provenance"]["config_sha256"]
    assert (
        first["provenance"]["evaluation_config_sha256"]
        == second["provenance"]["evaluation_config_sha256"]
    )
    registry = load_result_registry(
        _registry(
            tmp_path / "results",
            [(first, None, None), (second, None, "record-1")],
        )
    )
    assert [record.record_id for record in registry.records] == ["record-1", "record-2"]

    disposition = copy.deepcopy(first)
    disposition["record_id"] = "record-dispute"
    disposition["status"] = "disputed"
    registry = load_result_registry(
        _registry(
            tmp_path / "disposition",
            [(first, None, None), (disposition, "record-1", None)],
        )
    )
    assert registry.records[-1].result.run_id == "run-1"


def test_public_result_normalizes_integral_json_numbers(tmp_path: Path) -> None:
    payload = _result()
    payload["release"]["task_count"] = 1.0
    payload["quality"]["attempts_scored"] = 3.0
    payload["operations"]["total_input_tokens"] = 300.0
    payload["provenance"]["evaluation_config_sha256"] = evaluation_config_sha256(
        payload
    )

    loaded = load_public_result(_write(tmp_path / "result.json", payload))

    assert loaded.release["task_count"] == 1
    assert type(loaded.release["task_count"]) is int
    assert type(loaded.quality["attempts_scored"]) is int
    assert type(loaded.operations["total_input_tokens"]) is int


def test_registry_rejects_disposition_identity_change_and_reproduction_alias(
    tmp_path: Path,
) -> None:
    first = _result("record-1")
    changed = copy.deepcopy(first)
    changed.update({"record_id": "record-dispute", "status": "disputed"})
    changed["provenance"]["config_sha256"] = "9" * 64
    with pytest.raises(BenchmarkError, match="exact run/config"):
        load_result_registry(
            _registry(
                tmp_path / "changed",
                [(first, None, None), (changed, "record-1", None)],
            )
        )

    reproduced = _result("record-2", status="reproduced", run_id="run-2")
    with pytest.raises(BenchmarkError, match="reproduces relation"):
        load_result_registry(
            _registry(
                tmp_path / "alias",
                [(first, None, None), (reproduced, "record-1", None)],
            )
        )

    reproduced = _result("record-2", status="reproduced", run_id="run-2")
    reproduced["provenance"]["config_sha256"] = first["provenance"]["config_sha256"]
    with pytest.raises(BenchmarkError, match="distinct raw run configuration"):
        load_result_registry(
            _registry(
                tmp_path / "same-raw-config",
                [(first, None, None), (reproduced, None, "record-1")],
            )
        )


@pytest.mark.parametrize(
    "value,match",
    [
        (r"C:\\private\\answer.json", "absolute path"),
        ("/home/reviewer/private.json", "absolute path"),
        ("https://private.example.invalid/result", "URI"),
        ("Authorization: Bearer secret-token", "credential marker"),
        ("BENCHMARK_PRIVATE_CANARY", "private sentinel"),
        ("unsafe" + chr(1) + "text", "control character"),
    ],
)
def test_public_result_rejects_obvious_private_material(
    tmp_path: Path, value: str, match: str
) -> None:
    payload = _result()
    payload["subject"]["label"] = value
    with pytest.raises(BenchmarkError, match=match):
        load_public_result(_write(tmp_path / "result.json", payload))


def test_public_result_rejects_caller_supplied_private_sentinel(tmp_path: Path) -> None:
    payload = _result()
    payload["subject"]["label"] = "opaque-seed-4821"
    path = _write(tmp_path / "result.json", payload)
    with pytest.raises(BenchmarkError, match="private sentinel"):
        load_public_result(path, forbidden_sentinels=("seed-4821",))


def test_registry_rejects_unregistered_files_hash_changes_and_forks(tmp_path: Path) -> None:
    root = tmp_path / "results"
    path = _registry(root, [(_result("record-1"), None, None)])
    (root / "records" / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="inventory"):
        load_result_registry(path)

    (root / "records" / "extra.json").unlink()
    (root / "records" / "record-1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="digest"):
        load_result_registry(path)

    root = tmp_path / "fork"
    first = _result("record-1")
    second = copy.deepcopy(first)
    second.update({"record_id": "record-2", "status": "disputed"})
    third = copy.deepcopy(first)
    third.update({"record_id": "record-3", "status": "withdrawn"})
    path = _registry(
        root,
        [
            (first, None, None),
            (second, "record-1", None),
            (third, "record-1", None),
        ],
    )
    with pytest.raises(BenchmarkError, match="one direct superseder"):
        load_result_registry(path)


def test_registry_rejects_case_colliding_record_files(tmp_path: Path) -> None:
    root = tmp_path / "results"
    path = _registry(root, [(_result("record-1"), None, None)])
    collision = root / "records" / "RECORD-1.json"
    try:
        collision.write_text("{}", encoding="utf-8")
    except OSError:
        pytest.skip("filesystem does not permit case-colliding names")
    if collision.samefile(root / "records" / "record-1.json"):
        pytest.skip("filesystem is case-insensitive")
    with pytest.raises(BenchmarkError, match="case collision"):
        load_result_registry(path)


def test_git_base_comparison_allows_append_but_rejects_existing_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".gitattributes").write_text("results/** -text\n", encoding="utf-8")
    registry = _registry(repo / "results", [(_result("record-1"), None, None)])
    subprocess.run(["git", "add", "results"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    _registry(
        repo / "results",
        [
            (_result("record-1"), None, None),
            (_result("record-2", status="reproduced", run_id="run-2"), None, "record-1"),
        ],
    )
    validate_registry_against_git_base(registry, base)

    changed = copy.deepcopy(_result("record-1"))
    changed["quality"]["macro_recall"] = 0.5
    _registry(
        repo / "results",
        [
            (changed, None, None),
            (_result("record-2", status="reproduced", run_id="run-2"), None, "record-1"),
        ],
    )
    with pytest.raises(BenchmarkError, match="entry .* modified"):
        validate_registry_against_git_base(registry, base)


def test_registry_digest_is_exact_bytes_across_float_and_unicode_forms(tmp_path: Path) -> None:
    root = tmp_path / "results"
    payload = _result("record-unicode", run_id="run-unicode")
    payload["subject"]["label"] = "Review café \u2615"
    payload["provenance"]["evaluation_config_sha256"] = evaluation_config_sha256(
        payload
    )
    record = root / "records" / "record-unicode.json"
    record.parent.mkdir(parents=True)
    raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    record.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    registry = {
        "schema": "review-benchmark/result-registry/1",
        "records": [
            {
                "record_id": "record-unicode",
                "path": "records/record-unicode.json",
                "sha256": digest,
                "supersedes": None,
                "reproduces": None,
            }
        ],
    }
    registry_path = _write(root / "registry.json", registry)
    assert load_result_registry(registry_path).records[0].sha256 == digest

    alternate = raw.replace(b"1.0", b"1", 1)
    assert alternate != raw
    assert hashlib.sha256(alternate).hexdigest() != digest
