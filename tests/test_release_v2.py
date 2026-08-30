from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from review_benchmark.models import BenchmarkError
from review_benchmark.release import load_release

ROOT = Path(__file__).parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _official_release(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    destination = tmp_path / "official-release"
    shutil.copytree(ROOT / "fixtures" / "public-v0.4", destination)
    legacy = json.loads((destination / "MANIFEST.json").read_text(encoding="utf-8"))
    files = [
        path
        for path in destination.rglob("*")
        if path.is_file() and path.name != "MANIFEST.json"
    ]
    artifacts = [
        {
            "path": path.relative_to(destination).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha(path),
        }
        for path in sorted(files, key=lambda item: item.relative_to(destination).as_posix())
    ]
    manifest: dict[str, object] = {
        "schema": "review-benchmark/release/2",
        "release_id": "official-test-v1",
        "visibility": "public",
        "status": "official",
        "public_benchmark_revision": "a" * 40,
        "tasks": legacy["tasks"],
        "artifacts": artifacts,
    }
    (destination / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    return destination, manifest


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_loads_official_release_with_exact_inventory(tmp_path: Path) -> None:
    root, _ = _official_release(tmp_path)
    release = load_release(root)
    assert release.status == "official"
    assert release.public_benchmark_revision == "a" * 40
    assert len(release.tasks) == 2
    assert len(release.manifest_sha256) == 64


def test_release_normalizes_integral_json_number_sizes(tmp_path: Path) -> None:
    root, manifest = _official_release(tmp_path)
    manifest["artifacts"][0]["size_bytes"] = float(
        manifest["artifacts"][0]["size_bytes"]
    )
    _write_manifest(root, manifest)

    release = load_release(root)

    assert type(release.manifest["artifacts"][0]["size_bytes"]) is int


def test_legacy_calibration_release_remains_loadable() -> None:
    release = load_release(ROOT / "fixtures" / "public-v0.4")
    assert release.status == "calibration"
    assert release.public_benchmark_revision is None


def test_legacy_release_extensions_and_status_remain_loadable(tmp_path: Path) -> None:
    root, _ = _official_release(tmp_path)
    manifest = json.loads((root / "MANIFEST.json").read_text())
    manifest.pop("artifacts")
    manifest.pop("public_benchmark_revision")
    manifest["schema"] = "review-benchmark/release/1"
    manifest["status"] = "official"
    manifest["historical_extension"] = {"preserved": True}
    manifest["tasks"][0]["extension"] = "preserved"
    _write_manifest(root, manifest)
    release = load_release(root)
    assert release.status == "official"
    assert release.manifest["historical_extension"] == {"preserved": True}
    with pytest.raises(BenchmarkError, match="requires release/2"):
        load_release(root, require_official_contract=True)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda m: m.__setitem__("status", "calibration"), "status"),
        (lambda m: m.__setitem__("public_benchmark_revision", "short"), "Git SHA"),
        (lambda m: m.__setitem__("unexpected", True), "unexpected"),
        (
            lambda m: m["artifacts"].append(
                {"path": "../escape", "size_bytes": 0, "sha256": "0" * 64}
            ),
            "normalized",
        ),
        (
            lambda m: m["artifacts"][0].__setitem__(
                "size_bytes", 9_007_199_254_740_992
            ),
            "integer between",
        ),
    ],
)
def test_rejects_invalid_official_manifest(
    tmp_path: Path, mutation, match: str
) -> None:
    root, manifest = _official_release(tmp_path)
    mutation(manifest)
    _write_manifest(root, manifest)
    with pytest.raises(BenchmarkError, match=match):
        load_release(root)


def test_rejects_changed_or_unmanifested_artifacts(tmp_path: Path) -> None:
    root, _ = _official_release(tmp_path)
    target = root / "tasks" / "planted-mini" / "diff.patch"
    target.write_bytes(target.read_bytes() + b"\ntamper\n")
    with pytest.raises(BenchmarkError, match="size or digest"):
        load_release(root)

    root, _ = _official_release(tmp_path / "second")
    (root / "unmanifested.txt").write_text("surprise", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="not exact"):
        load_release(root)


def test_rejects_case_colliding_and_duplicate_manifest_paths(tmp_path: Path) -> None:
    root, manifest = _official_release(tmp_path)
    manifest["artifacts"] = [
        {"path": "A", "size_bytes": 0, "sha256": "0" * 64},
        {"path": "a", "size_bytes": 0, "sha256": "0" * 64},
    ]
    _write_manifest(root, manifest)
    with pytest.raises(BenchmarkError, match="case-colliding"):
        load_release(root)


def test_rejects_link_without_reading_external_target(tmp_path: Path) -> None:
    root, _ = _official_release(tmp_path)
    external = tmp_path / "external.txt"
    external.write_text("do not read", encoding="utf-8")
    link = root / "linked.txt"
    try:
        os.symlink(external, link)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")
    with pytest.raises(BenchmarkError, match="link or reparse"):
        load_release(root)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction-specific regression")
def test_rejects_windows_junction_without_traversal(tmp_path: Path) -> None:
    root, _ = _official_release(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.txt").write_text("outside", encoding="utf-8")
    junction = root / "junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode:
        pytest.skip("junction creation is unavailable in this environment")
    with pytest.raises(BenchmarkError, match="link or reparse"):
        load_release(root)
