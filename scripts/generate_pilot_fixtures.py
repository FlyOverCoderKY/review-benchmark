"""Generate the public v0.1 planted/clean calibration family.

The same base tree is changed two ways: one deliberately defective and one
correct. Run without arguments to regenerate committed artifacts, or with
``--check`` to compare a temporary regeneration with the committed release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = ROOT / "fixtures" / "public-v0.1"
TASKS_ROOT = RELEASE_ROOT / "tasks"

BASE = {
    "calc.py": '''"""Contribution calculations for a small benefits service."""

CAPS = {2026: 8_300}


def apply_cap(amount: int, year: int = 2026) -> int:
    return min(amount, CAPS[year])


def contribution_total(amounts: list[int]) -> int:
    for amount in amounts:
        if amount < 0:
            raise ValueError("amount must be non-negative")
    return sum(amounts)
''',
    "report.py": '''"""Annual report assembly."""

from calc import apply_cap, contribution_total


def annual_report(amounts: list[int], year: int) -> dict[str, int]:
    capped = apply_cap(contribution_total(amounts))
    return {"year": year, "capped_total": capped}
''',
    "rules.py": '''"""The independently maintained plan-year registry."""

SUPPORTED_YEARS = (2026,)
''',
    "tests/test_calc.py": '''from calc import apply_cap, contribution_total
from report import annual_report


def test_2026_cap() -> None:
    assert apply_cap(9_000, 2026) == 8_300


def test_negative_amount() -> None:
    try:
        contribution_total([100, -1])
    except ValueError:
        return
    raise AssertionError("negative amount accepted")


def test_2026_report() -> None:
    assert annual_report([9_000], 2026)["capped_total"] == 8_300
''',
}

PLANTED = {
    "calc.py": '''"""Contribution calculations for a small benefits service."""

CAPS = {2026: 8_300, 2027: 8_300}


def apply_cap(amount: int, year: int = 2026) -> int:
    return min(amount, CAPS[year])


def contribution_total(amounts: list[int]) -> int:
    return sum(amounts)


def average_contribution(amounts: list[int]) -> float:
    return contribution_total(amounts) / len(amounts)
''',
    "report.py": BASE["report.py"],
    "rules.py": '''"""The independently maintained plan-year registry."""

SUPPORTED_YEARS = (2026,)
''',
    "tests/test_calc.py": '''from calc import apply_cap, average_contribution, contribution_total
from report import annual_report


def test_2026_cap() -> None:
    assert apply_cap(9_000, 2026) == 8_300


def test_2027_cap_uses_table() -> None:
    assert apply_cap(9_000, 2027) == 8_300


def test_average() -> None:
    assert average_contribution([100, 300]) == 200


def test_negative_amount() -> None:
    try:
        contribution_total([100, -1])
    except ValueError:
        return
    raise AssertionError("negative amount accepted")


def test_2027_report_uses_new_year() -> None:
    assert annual_report([9_000], 2027)["year"] == 2027
''',
}

CLEAN = {
    "calc.py": '''"""Contribution calculations for a small benefits service."""

CAPS = {2026: 8_300, 2027: 8_550}


def apply_cap(amount: int, year: int = 2026) -> int:
    if year not in CAPS:
        raise ValueError(f"unsupported year {year}")
    return min(amount, CAPS[year])


def contribution_total(amounts: list[int]) -> int:
    for amount in amounts:
        if amount < 0:
            raise ValueError("amount must be non-negative")
    return sum(amounts)


def average_contribution(amounts: list[int]) -> float:
    if not amounts:
        raise ValueError("amounts must not be empty")
    return contribution_total(amounts) / len(amounts)
''',
    "report.py": '''"""Annual report assembly."""

from calc import apply_cap, contribution_total
from rules import SUPPORTED_YEARS


def annual_report(amounts: list[int], year: int) -> dict[str, int]:
    if year not in SUPPORTED_YEARS:
        raise ValueError(f"unsupported year {year}")
    capped = apply_cap(contribution_total(amounts), year)
    return {"year": year, "capped_total": capped}
''',
    "rules.py": '''"""The independently maintained plan-year registry."""

SUPPORTED_YEARS = (2026, 2027)
''',
    "tests/test_calc.py": '''from calc import apply_cap, average_contribution, contribution_total
from report import annual_report


def test_2026_cap() -> None:
    assert apply_cap(9_000, 2026) == 8_300


def test_2027_cap() -> None:
    assert apply_cap(9_000, 2027) == 8_550


def test_average() -> None:
    assert average_contribution([100, 300]) == 200


def test_average_rejects_empty() -> None:
    try:
        average_contribution([])
    except ValueError:
        return
    raise AssertionError("empty input accepted")


def test_negative_amount() -> None:
    try:
        contribution_total([100, -1])
    except ValueError:
        return
    raise AssertionError("negative amount accepted")


def test_2027_report() -> None:
    assert annual_report([9_000], 2027)["capped_total"] == 8_550
''',
}

GOLD = [
    {
        "id": "PM-B1",
        "title": "The 2027 cap repeats the 2026 amount",
        "severity": "bug",
        "context": "diff",
        "defect_statement": "The new 2027 constant is stale at 8,300 instead of 8,550.",
        "trigger": "Apply the cap to a 2027 contribution above 8,300.",
        "impact": "Valid 2027 contributions are under-counted by as much as 250.",
        "proof": ["clean twin test_2027_cap", "independent fixture specification"],
        "match": {
            "paths": ["calc.py"],
            "keywords": ["2027.{0,100}(8[_,]?300|stale|same.{0,20}2026)", "cap.{0,80}8[_,]?550"],
        },
    },
    {
        "id": "PM-B2",
        "title": "Negative contributions are no longer rejected",
        "severity": "bug",
        "context": "diff",
        "defect_statement": "contribution_total removed the non-negative validation.",
        "trigger": "Call contribution_total with a negative element.",
        "impact": "Invalid negative contributions silently reduce the total.",
        "proof": ["base negative-amount test", "clean twin negative-amount test"],
        "match": {
            "paths": ["calc.py"],
            "keywords": [
                "negative.{0,100}(valid|reject|accept)",
                "validation.{0,100}contribution_total",
            ],
        },
    },
    {
        "id": "PM-B3",
        "title": "Average crashes on an empty list",
        "severity": "risk",
        "context": "diff",
        "defect_statement": (
            "average_contribution divides by len(amounts) without an empty-input guard."
        ),
        "trigger": "Call average_contribution([]).",
        "impact": "A valid empty collection causes ZeroDivisionError instead of a domain error.",
        "proof": ["clean twin test_average_rejects_empty"],
        "match": {
            "paths": ["calc.py"],
            "keywords": ["(empty|zero).{0,100}(average|division|len)", "ZeroDivisionError"],
        },
    },
    {
        "id": "PM-B4",
        "title": "Annual reports ignore their requested plan year",
        "severity": "bug",
        "context": "file",
        "defect_statement": "annual_report still calls apply_cap without forwarding year.",
        "trigger": "Generate a 2027 report for a contribution above the 2026 cap.",
        "impact": "The report labels output as 2027 while calculating with 2026 rules.",
        "proof": ["clean twin test_2027_report", "report.py call path"],
        "match": {
            "paths": ["report.py"],
            "keywords": [
                "(ignore|omit|forward|pass).{0,100}year",
                "default.{0,100}(2026|plan year)",
            ],
        },
    },
    {
        "id": "PM-B5",
        "title": "The supported-year registry omits 2027",
        "severity": "risk",
        "context": "repo",
        "defect_statement": "CAPS accepts 2027 while rules.SUPPORTED_YEARS still lists only 2026.",
        "trigger": "A caller validates 2027 against the repository rule registry.",
        "impact": "Different code paths disagree about whether 2027 is supported.",
        "proof": ["clean twin rules.py", "cross-file registry invariant"],
        "match": {
            "paths": ["rules.py", "calc.py"],
            "keywords": [
                "SUPPORTED_YEARS.{0,200}(2027|not updated|disagree|diverge)",
                "registry.{0,100}(omit|missing|inconsistent|disagree|diverge)",
            ],
        },
    },
]


def write_tree(root: Path, tree: dict[str, str]) -> None:
    for relative, content in tree.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.email=bench@example.invalid",
            "-c",
            "user.name=Benchmark Fixture",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def render_diff(head: dict[str, str]) -> str:
    with tempfile.TemporaryDirectory(prefix="review-benchmark-fixture.") as temporary:
        repo = Path(temporary) / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        write_tree(repo, BASE)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        for relative in BASE:
            (repo / relative).unlink()
        write_tree(repo, head)
        git(repo, "add", "-A")
        return git(repo, "diff", "--cached", "--no-color", "--no-ext-diff")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_task(root: Path, name: str, tree: dict[str, str], *, clean: bool) -> None:
    task_root = root / "tasks" / name
    checkout = task_root / "checkout"
    if checkout.exists():
        resolved = checkout.resolve()
        expected_parent = (root / "tasks" / name).resolve()
        if resolved.parent != expected_parent:
            raise RuntimeError(f"refusing to replace unexpected checkout: {resolved}")
        shutil.rmtree(checkout)
    write_tree(checkout, tree)
    (task_root / "diff.patch").write_text(render_diff(tree), encoding="utf-8", newline="\n")
    write_json(
        task_root / "gold.json",
        {
            "schema": "review-benchmark/gold/1",
            "task_id": name,
            "completeness": "synthetic-complete",
            "findings": [] if clean else GOLD,
        },
    )
    write_json(
        task_root / "adjudications.json",
        {
            "schema": "review-benchmark/adjudications/1",
            "task_id": name,
            "findings": [],
        },
    )
    write_json(
        task_root / "task.json",
        {
            "schema": "review-benchmark/task/1",
            "task_id": name,
            "title": "Mini benefits change (clean control)" if clean else "Mini benefits change",
            "family_id": "planted-mini-family",
            "origin": "clean-control" if clean else "planted",
            "language": "python",
            "visibility": "public",
            "source": {
                "kind": "synthetic",
                "repository": "https://github.com/FlyOverCoderKY/review-benchmark",
                "license_spdx": "MIT",
                "generator": "scripts/generate_pilot_fixtures.py",
            },
            "files": {
                "diff": "diff.patch",
                "checkout": "checkout",
                "gold": "gold.json",
                "adjudications": "adjudications.json",
            },
            "context": {
                "minimum_classes": ["diff", "file", "repo"] if not clean else [],
                "reviewer_access": ["diff", "checkout"],
                "code_execution": False,
                "network": False,
            },
        },
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(root: Path) -> None:
    write_task(root, "planted-mini", PLANTED, clean=False)
    write_task(root, "planted-mini-clean", CLEAN, clean=True)
    tasks = []
    for name in ("planted-mini", "planted-mini-clean"):
        task_path = root / "tasks" / name / "task.json"
        tasks.append(
            {
                "task_id": name,
                "path": f"tasks/{name}",
                "task_manifest_sha256": sha256(task_path),
            }
        )
    write_json(
        root / "MANIFEST.json",
        {
            "schema": "review-benchmark/release/1",
            "release_id": "public-v0.1",
            "status": "calibration",
            "visibility": "public",
            "generated_with": "scripts/generate_pilot_fixtures.py",
            "tasks": tasks,
        },
    )


def files_under(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def check() -> int:
    with tempfile.TemporaryDirectory(prefix="review-benchmark-check.") as temporary:
        generated = Path(temporary) / "public-v0.1"
        generate(generated)
        expected = files_under(generated)
        actual = files_under(RELEASE_ROOT) if RELEASE_ROOT.exists() else {}
    if expected == actual:
        print("public-v0.1 fixtures are reproducible")
        return 0
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    changed = sorted(path for path in set(actual) & set(expected) if actual[path] != expected[path])
    print(f"fixture drift: missing={missing}, unexpected={unexpected}, changed={changed}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()
    generate(RELEASE_ROOT)
    print(f"generated {RELEASE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
