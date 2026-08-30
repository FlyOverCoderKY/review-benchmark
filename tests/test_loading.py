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


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "findings.json"
    path.write_text(
        '{"schema":"review-benchmark/findings/1","schema":"duplicate",'
        '"task_id":"task-1","attempt_id":"a1","findings":[]}',
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkError, match="duplicate object key"):
        load_findings(path)


@pytest.mark.parametrize(
    ("value", "match"),
    [("NaN", "non-finite"), ('"\\ud800"', "Unicode surrogate")],
)
def test_nonstandard_numbers_and_unpaired_unicode_are_rejected(
    tmp_path: Path, value: str, match: str
) -> None:
    path = tmp_path / "findings.json"
    path.write_text(
        '{"schema":"review-benchmark/findings/1","task_id":"task-1",'
        f'"attempt_id":{value},"findings":[]}}',
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkError, match=match):
        load_findings(path)
