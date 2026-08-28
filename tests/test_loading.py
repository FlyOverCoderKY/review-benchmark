from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_benchmark.models import BenchmarkError, load_findings, normalize_relative_path


@pytest.mark.parametrize("path", ["../secret", "/absolute", "./not-normalized", "a/../../b"])
def test_paths_must_be_confined_and_normalized(path: str) -> None:
    with pytest.raises(BenchmarkError):
        normalize_relative_path(path, "path")


def test_findings_are_bound_to_task(tmp_path: Path) -> None:
    path = tmp_path / "findings.json"
    path.write_text(
        json.dumps(
            {
                "schema": "review-benchmark/findings/1",
                "task_id": "wrong",
                "attempt_id": "a1",
                "findings": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkError, match="does not match"):
        load_findings(path, expected_task_id="expected")
