from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from review_benchmark.models import _json_loads

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("path", sorted((ROOT / "schemas").glob("*.json")))
def test_every_published_json_schema_is_valid(path: Path) -> None:
    schema = _json_loads(path.read_text(encoding="utf-8"), f"schema {path}")
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "public-result.schema.json",
            "dbfd5daca6e486c860ffe0f03da5add7bc854c1e1e8ae9f03cfaed4d439e1595",
        ),
        (
            "semantic-matcher-decisions.schema.json",
            "640df304e72fd27cd34972afef79ae3160bb7bc442e3f6dc8b7aa2d46ef59981",
        ),
        (
            "semantic-conformance-evaluation.schema.json",
            "c31e5704fdf66b8cb03c535e5f631a5677949e44e2e87cfd124461ee1d081037",
        ),
    ],
)
def test_published_v1_schema_bytes_remain_frozen(name: str, expected: str) -> None:
    assert hashlib.sha256((ROOT / "schemas" / name).read_bytes()).hexdigest() == expected
