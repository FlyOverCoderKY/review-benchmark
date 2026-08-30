"""Typed public result and append-only registry validation."""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review_benchmark.models import (
    BenchmarkError,
    _json_loads,
    _read_json,
    _require_dict,
    _require_keys,
    _require_list,
    _require_str,
)
from review_benchmark.release import _is_reparse
from review_benchmark.run_adjudications import canonical_sha256

PUBLIC_RESULT_SCHEMA = "review-benchmark/public-result/2"
RESULT_REGISTRY_SCHEMA = "review-benchmark/result-registry/1"
EVALUATION_CONFIG_SCHEMA = "review-benchmark/evaluation-config-fingerprint/1"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_STATUSES = {
    "provisional",
    "official",
    "reproduced",
    "superseded",
    "withdrawn",
    "disputed",
}
_TRACKS = {"fixed-harness-model", "end-to-end-product"}
_OFFICIAL_STATUSES = {"official", "reproduced"}
_DISPOSITION_STATUSES = {"superseded", "withdrawn", "disputed"}
_URI_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?:^|[\s\"'(])(?:[a-z]:[\\/]|\\\\)")
_POSIX_ABSOLUTE_RE = re.compile(
    r"(?i)(?:^|[\s\"'(])/(?:home|users|tmp|var|etc|root|mnt|opt|workspace|private)(?:/|\b)"
)
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:\bapi[_ -]?key\b|authorization\s*:|bearer\s+[a-z0-9]|"
    r"password\s*=|secret\s*=|begin [a-z ]*private key|"
    r"\bgh[pousr]_[a-z0-9]{8,}|\bsk-[a-z0-9]{8,}|\bxai-[a-z0-9]{8,})"
)
_BUILTIN_SENTINELS = (
    "benchmark_private_canary",
    "private_canary",
    "do_not_publish",
    "coordinator-only",
)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _id(value: object, label: str) -> str:
    result = _require_str(value, label)
    if _ID_RE.fullmatch(result) is None:
        raise BenchmarkError(f"{label} must be a normalized identifier")
    return result


def _digest(value: object, label: str, pattern: re.Pattern[str] = _SHA256_RE) -> str:
    result = _require_str(value, label)
    if pattern.fullmatch(result) is None:
        raise BenchmarkError(f"{label} has an invalid digest")
    return result


def _count(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
        or float(value) < 0
        or float(value) > _MAX_SAFE_INTEGER
    ):
        raise BenchmarkError(
            f"{label} must be an integer between 0 and {_MAX_SAFE_INTEGER}"
        )
    return int(value)


def _nullable_count(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _count(value, label)


def _number(value: object, label: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        suffix = " or null" if nullable else ""
        raise BenchmarkError(f"{label} must be a finite number >= 0{suffix}")
    return float(value)


def _ratio(value: object, label: str, *, nullable: bool = True) -> float | None:
    result = _number(value, label, nullable=nullable)
    if result is not None and result > 1:
        raise BenchmarkError(f"{label} must be between 0 and 1")
    return result


def _bounded_string(value: object, label: str, maximum: int) -> str:
    result = _require_str(value, label)
    if len(result) > maximum:
        raise BenchmarkError(f"{label} must contain at most {maximum} characters")
    return result


def _bounded_nullable_string(value: object, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _bounded_string(value, label, maximum)


def _exact_ratio(value: float | None, numerator: int, denominator: int, label: str) -> None:
    if denominator == 0:
        if value is not None:
            raise BenchmarkError(f"{label} must be null when its denominator is zero")
    elif value is None or not math.isclose(value, numerator / denominator, abs_tol=1e-12):
        raise BenchmarkError(f"{label} does not match its numerator and denominator")


def _exact_mean(
    value: float | None, total: float | int | None, denominator: int, label: str
) -> None:
    if denominator == 0 or total is None:
        if value is not None:
            raise BenchmarkError(f"{label} must be null without a complete denominator")
    elif value is None or not math.isclose(value, float(total) / denominator, abs_tol=1e-12):
        raise BenchmarkError(f"{label} does not match its total and denominator")


def assert_public_safe(
    payload: object, *, forbidden_sentinels: tuple[str, ...] = ()
) -> None:
    """Reject obvious private material before a result crosses the public boundary."""

    sentinels = tuple(
        marker.casefold()
        for marker in (*_BUILTIN_SENTINELS, *forbidden_sentinels)
        if isinstance(marker, str) and marker
    )

    def visit(value: object, label: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{label}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{label}[{index}]")
        elif isinstance(value, str):
            if any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise BenchmarkError(f"{label} contains a control character")
            if _URI_RE.search(value):
                raise BenchmarkError(f"{label} contains a URI")
            if _WINDOWS_ABSOLUTE_RE.search(value) or _POSIX_ABSOLUTE_RE.search(value):
                raise BenchmarkError(f"{label} contains an absolute path")
            if _CREDENTIAL_RE.search(value):
                raise BenchmarkError(f"{label} contains a credential marker")
            folded = value.casefold()
            if any(marker in folded for marker in sentinels):
                raise BenchmarkError(f"{label} contains a private sentinel")

    visit(payload, "public result")


def evaluation_config_sha256(payload: dict[str, Any]) -> str:
    """Fingerprint stable evaluation identity, excluding run/publication metadata."""

    subject = _require_dict(payload.get("subject"), "evaluation config subject")
    release = _require_dict(payload.get("release"), "evaluation config release")
    provenance = _require_dict(
        payload.get("provenance"), "evaluation config provenance"
    )
    return canonical_sha256(
        {
            "schema": EVALUATION_CONFIG_SCHEMA,
            "track": payload.get("track"),
            "subject": {
                field: subject.get(field)
                for field in (
                    "adapter",
                    "label",
                    "model",
                    "provider",
                    "expected_reported_provider",
                    "effort",
                    "fallbacks_disabled",
                )
            },
            "release": {
                "id": release.get("id"),
                "visibility": release.get("visibility"),
                "task_count": _count(
                    release.get("task_count"), "evaluation config release.task_count"
                ),
                "attempts_per_task": _count(
                    release.get("attempts_per_task"),
                    "evaluation config release.attempts_per_task",
                ),
            },
            "evaluation_provenance": {
                field: provenance.get(field)
                for field in (
                    "scorer_git_sha",
                    "public_benchmark_git_sha",
                    "release_git_sha",
                    "product_git_sha",
                    "release_manifest_sha256",
                    "scorer_version",
                    "provider_policy",
                )
            },
        }
    )


@dataclass(frozen=True)
class PublicResult:
    record_id: str
    run_id: str
    status: str
    track: str
    subject: dict[str, Any]
    release: dict[str, Any]
    provenance: dict[str, Any]
    quality: dict[str, Any]
    operations: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class RegistryRecord:
    record_id: str
    path: str
    sha256: str
    supersedes: str | None
    reproduces: str | None
    result: PublicResult


@dataclass(frozen=True)
class ResultRegistry:
    root: Path
    records: tuple[RegistryRecord, ...]
    raw: dict[str, Any]


def _validate_subject(value: object) -> dict[str, Any]:
    item = _require_dict(value, "public result.subject")
    _require_keys(
        item,
        "public result.subject",
        required={
            "adapter",
            "label",
            "model",
            "provider",
            "expected_reported_provider",
            "effort",
            "fallbacks_disabled",
        },
    )
    _id(item.get("adapter"), "public result.subject.adapter")
    _bounded_string(item.get("label"), "public result.subject.label", 200)
    _bounded_string(item.get("model"), "public result.subject.model", 300)
    _bounded_nullable_string(item.get("provider"), "public result.subject.provider", 200)
    _bounded_nullable_string(
        item.get("expected_reported_provider"),
        "public result.subject.expected_reported_provider",
        200,
    )
    _bounded_nullable_string(item.get("effort"), "public result.subject.effort", 100)
    if not isinstance(item.get("fallbacks_disabled"), bool):
        raise BenchmarkError("public result.subject.fallbacks_disabled must be a boolean")
    return item


def _validate_release(value: object) -> dict[str, Any]:
    item = _require_dict(value, "public result.release")
    _require_keys(
        item,
        "public result.release",
        required={"id", "visibility", "task_count", "attempts_per_task"},
    )
    _bounded_string(item.get("id"), "public result.release.id", 200)
    if item.get("visibility") not in {"public", "private"}:
        raise BenchmarkError("public result.release.visibility is invalid")
    item["task_count"] = _count(
        item.get("task_count"), "public result.release.task_count"
    )
    if item["task_count"] < 1:
        raise BenchmarkError("public result.release.task_count must be >= 1")
    item["attempts_per_task"] = _count(
        item.get("attempts_per_task"), "public result.release.attempts_per_task"
    )
    if item["attempts_per_task"] < 1:
        raise BenchmarkError("public result.release.attempts_per_task must be >= 1")
    return item


def _validate_provenance(value: object) -> dict[str, Any]:
    item = _require_dict(value, "public result.provenance")
    git_fields = {
        "runner_git_sha",
        "scorer_git_sha",
        "public_benchmark_git_sha",
        "release_git_sha",
        "product_git_sha",
    }
    _require_keys(
        item,
        "public result.provenance",
        required={
            *git_fields,
            "config_sha256",
            "evaluation_config_sha256",
            "release_manifest_sha256",
            "scorer_version",
            "provider_policy",
        },
    )
    for field in git_fields:
        _digest(item.get(field), f"public result.provenance.{field}", _GIT_SHA_RE)
    _digest(item.get("config_sha256"), "public result.provenance.config_sha256")
    _digest(
        item.get("evaluation_config_sha256"),
        "public result.provenance.evaluation_config_sha256",
    )
    _digest(
        item.get("release_manifest_sha256"),
        "public result.provenance.release_manifest_sha256",
    )
    _bounded_string(
        item.get("scorer_version"), "public result.provenance.scorer_version", 200
    )
    _bounded_string(
        item.get("provider_policy"), "public result.provenance.provider_policy", 2000
    )
    if item["scorer_git_sha"] != item["public_benchmark_git_sha"]:
        raise BenchmarkError("scorer Git SHA must equal public benchmark Git SHA")
    return item


def _validate_quality(value: object, attempts_per_task: int) -> dict[str, Any]:
    item = _require_dict(value, "public result.quality")
    scalar_ratios = {
        "macro_recall",
        "macro_adjudicated_precision",
        "clean_pass_rate",
        "severity_agreement",
    }
    counts = {
        "attempts_scored",
        "gold_findings",
        "matched_findings",
        "missed_findings",
        "valid_extra_findings",
        "false_positive_findings",
        "duplicate_findings",
        "pending_findings",
        "clean_reviews",
        "clean_reviews_passed",
    }
    _require_keys(
        item,
        "public result.quality",
        required={
            *scalar_ratios,
            *counts,
            "mean_noise_count",
            "severity_recall",
            "attempt_detection_frequency",
        },
    )
    for field in scalar_ratios:
        _ratio(item.get(field), f"public result.quality.{field}")
    _number(item.get("mean_noise_count"), "public result.quality.mean_noise_count", nullable=True)
    for field in counts:
        item[field] = _count(item.get(field), f"public result.quality.{field}")
    if item["matched_findings"] + item["missed_findings"] != item["gold_findings"]:
        raise BenchmarkError("public result quality matched + missed must equal gold findings")
    if item["clean_reviews_passed"] > item["clean_reviews"]:
        raise BenchmarkError("public result clean reviews passed exceeds clean reviews")
    if item["clean_reviews"] > item["attempts_scored"]:
        raise BenchmarkError("public result clean reviews exceeds scored attempts")
    if item["clean_reviews"] % attempts_per_task:
        raise BenchmarkError("public result clean reviews must contain complete task attempts")
    _exact_ratio(
        item["clean_pass_rate"],
        item["clean_reviews_passed"],
        item["clean_reviews"],
        "public result.quality.clean_pass_rate",
    )

    severity = _require_dict(item.get("severity_recall"), "quality.severity_recall")
    _require_keys(severity, "quality.severity_recall", required={"bug", "risk", "nit"})
    severity_total = 0
    severity_matched = 0
    for name in ("bug", "risk", "nit"):
        bucket = _require_dict(severity.get(name), f"quality.severity_recall.{name}")
        _require_keys(
            bucket,
            f"quality.severity_recall.{name}",
            required={"matched", "total", "recall"},
        )
        matched = _count(bucket.get("matched"), f"severity_recall.{name}.matched")
        total = _count(bucket.get("total"), f"severity_recall.{name}.total")
        bucket["matched"] = matched
        bucket["total"] = total
        if matched > total:
            raise BenchmarkError(f"severity_recall.{name}.matched exceeds total")
        recall = _ratio(bucket.get("recall"), f"severity_recall.{name}.recall")
        _exact_ratio(recall, matched, total, f"severity_recall.{name}.recall")
        severity_total += total
        severity_matched += matched
    if severity_total != item["gold_findings"] or severity_matched != item["matched_findings"]:
        raise BenchmarkError("severity recall counts do not match headline finding counts")

    frequency = _require_dict(
        item.get("attempt_detection_frequency"), "quality.attempt_detection_frequency"
    )
    _require_keys(
        frequency,
        "quality.attempt_detection_frequency",
        required={
            "mean",
            "minimum",
            "maximum",
            "gold_findings",
            "detected_every_attempt",
            "detected_some_attempts",
            "never_detected",
        },
    )
    unique_gold = _count(frequency.get("gold_findings"), "detection_frequency.gold_findings")
    frequency["gold_findings"] = unique_gold
    category_fields = (
        "detected_every_attempt",
        "detected_some_attempts",
        "never_detected",
    )
    categories = []
    for field in category_fields:
        normalized = _count(frequency.get(field), f"detection_frequency.{field}")
        frequency[field] = normalized
        categories.append(normalized)
    if sum(categories) != unique_gold:
        raise BenchmarkError("detection frequency categories must sum to gold findings")
    if unique_gold * attempts_per_task != item["gold_findings"]:
        raise BenchmarkError("detection frequency gold count does not match repeated attempts")
    ratios = [
        _ratio(frequency.get(field), f"detection_frequency.{field}")
        for field in ("mean", "minimum", "maximum")
    ]
    if unique_gold == 0:
        if any(ratio is not None for ratio in ratios):
            raise BenchmarkError("detection frequencies must be null without gold findings")
    elif any(ratio is None for ratio in ratios):
        raise BenchmarkError("detection frequencies must be present with gold findings")
    elif not ratios[1] <= ratios[0] <= ratios[2]:
        raise BenchmarkError("detection frequency minimum/mean/maximum are inconsistent")
    elif not math.isclose(
        ratios[0] * item["gold_findings"],
        item["matched_findings"],
        abs_tol=1e-12,
    ):
        raise BenchmarkError("mean detection frequency does not match finding counts")
    elif any(
        not math.isclose(ratio * attempts_per_task, round(ratio * attempts_per_task))
        for ratio in ratios[1:]
    ):
        raise BenchmarkError("detection frequency bounds are not possible attempt counts")
    if categories[0] and ratios[2] != 1:
        raise BenchmarkError("detection frequency maximum must be 1 for always-detected findings")
    if categories[2] and ratios[1] != 0:
        raise BenchmarkError("detection frequency minimum must be 0 for never-detected findings")
    if not categories[0] and ratios[2] == 1:
        raise BenchmarkError("detection frequency maximum cannot be 1 without always detection")
    if not categories[2] and ratios[1] == 0:
        raise BenchmarkError("detection frequency minimum cannot be 0 without never detection")
    return item


def _validate_operations(value: object) -> dict[str, Any]:
    item = _require_dict(value, "public result.operations")
    counts = {
        "reviews_attempted",
        "reviews_with_telemetry",
        "costs_reported",
        "attempt_failures",
        "attempts_skipped",
    }
    nullable_numbers = {
        "median_elapsed_ms",
        "mean_input_tokens",
        "mean_output_tokens",
        "mean_cost_usd",
        "total_cost_usd",
        "known_cost_usd",
    }
    nullable_counts = {
        "total_elapsed_ms",
        "known_elapsed_ms",
        "total_input_tokens",
        "total_output_tokens",
        "total_cached_tokens",
    }
    _require_keys(
        item,
        "public result.operations",
        required={
            *counts,
            *nullable_numbers,
            *nullable_counts,
            "providers",
            "cost_guard_triggered",
            "observed_cost_usd",
        },
    )
    for field in counts:
        item[field] = _count(item.get(field), f"public result.operations.{field}")
    for field in nullable_numbers:
        _number(item.get(field), f"public result.operations.{field}", nullable=True)
    for field in nullable_counts:
        item[field] = _nullable_count(
            item.get(field), f"public result.operations.{field}"
        )
    _number(item.get("observed_cost_usd"), "public result.operations.observed_cost_usd")
    if not isinstance(item.get("cost_guard_triggered"), bool):
        raise BenchmarkError("public result.operations.cost_guard_triggered must be boolean")
    providers = _require_list(item.get("providers"), "public result.operations.providers")
    if len(providers) > 100:
        raise BenchmarkError("public result.operations.providers has too many entries")
    normalized = [
        _bounded_string(
            provider, f"public result.operations.providers[{index}]", 200
        )
        for index, provider in enumerate(providers)
    ]
    if normalized != sorted(set(normalized)):
        raise BenchmarkError("public result.operations.providers must be unique and sorted")
    if item["reviews_with_telemetry"] > item["reviews_attempted"]:
        raise BenchmarkError("reviews_with_telemetry exceeds reviews_attempted")
    if item["costs_reported"] > item["reviews_attempted"]:
        raise BenchmarkError("costs_reported exceeds reviews_attempted")
    return item


def load_public_result(
    path: Path, *, forbidden_sentinels: tuple[str, ...] = ()
) -> PublicResult:
    path = Path(path).absolute()
    if _is_reparse(path):
        raise BenchmarkError("public result must not be a link or reparse point")
    payload = _require_dict(_read_json(path, "public result"), "public result")
    assert_public_safe(payload, forbidden_sentinels=forbidden_sentinels)
    _require_keys(
        payload,
        "public result",
        required={
            "schema",
            "record_id",
            "run_id",
            "status",
            "track",
            "subject",
            "release",
            "provenance",
            "quality",
            "operations",
        },
    )
    if payload.get("schema") != PUBLIC_RESULT_SCHEMA:
        raise BenchmarkError(f"public result.schema must be {PUBLIC_RESULT_SCHEMA!r}")
    record_id = _id(payload.get("record_id"), "public result.record_id")
    run_id = _id(payload.get("run_id"), "public result.run_id")
    status = _require_str(payload.get("status"), "public result.status")
    if status not in _STATUSES:
        raise BenchmarkError("public result.status is invalid")
    track = _require_str(payload.get("track"), "public result.track")
    if track not in _TRACKS:
        raise BenchmarkError("public result.track is invalid")
    subject = _validate_subject(payload.get("subject"))
    release = _validate_release(payload.get("release"))
    provenance = _validate_provenance(payload.get("provenance"))
    quality = _validate_quality(payload.get("quality"), release["attempts_per_task"])
    operations = _validate_operations(payload.get("operations"))
    if provenance["evaluation_config_sha256"] != evaluation_config_sha256(payload):
        raise BenchmarkError(
            "public result.provenance.evaluation_config_sha256 does not match "
            "stable evaluation identity"
        )
    expected_attempts = release["task_count"] * release["attempts_per_task"]
    if operations["reviews_attempted"] != expected_attempts:
        raise BenchmarkError("reviews_attempted does not match release execution matrix")
    if quality["attempts_scored"] + operations["attempt_failures"] + operations[
        "attempts_skipped"
    ] != expected_attempts:
        raise BenchmarkError("scored, failed, and skipped attempts do not fill the run matrix")
    if operations["reviews_with_telemetry"] != (
        quality["attempts_scored"] + operations["attempt_failures"]
    ):
        raise BenchmarkError("telemetry count does not match dispatched attempt outcomes")
    telemetry_count = operations["reviews_with_telemetry"]
    if telemetry_count == 0:
        if operations["providers"]:
            raise BenchmarkError("zero telemetry requires an empty provider set")
        if any(
            operations[field] is not None
            for field in (
                "median_elapsed_ms",
                "known_elapsed_ms",
                "mean_input_tokens",
                "total_input_tokens",
                "mean_output_tokens",
                "total_output_tokens",
                "total_cached_tokens",
            )
        ):
            raise BenchmarkError("zero telemetry requires null timing and token aggregates")
    else:
        if not operations["providers"]:
            raise BenchmarkError("reported telemetry requires a non-empty provider set")
        for field in (
            "median_elapsed_ms",
            "known_elapsed_ms",
            "total_input_tokens",
            "total_output_tokens",
            "total_cached_tokens",
        ):
            if operations[field] is None:
                raise BenchmarkError(f"reported telemetry requires {field}")
        _exact_mean(
            operations["mean_input_tokens"],
            operations["total_input_tokens"],
            telemetry_count,
            "public result.operations.mean_input_tokens",
        )
        _exact_mean(
            operations["mean_output_tokens"],
            operations["total_output_tokens"],
            telemetry_count,
            "public result.operations.mean_output_tokens",
        )
        if operations["total_cached_tokens"] > operations["total_input_tokens"]:
            raise BenchmarkError("cached tokens cannot exceed total input tokens")
        if operations["median_elapsed_ms"] > operations["known_elapsed_ms"]:
            raise BenchmarkError("median elapsed time cannot exceed known elapsed time")
    costs_reported = operations["costs_reported"]
    known_cost = operations["known_cost_usd"]
    _exact_mean(
        operations["mean_cost_usd"],
        known_cost,
        costs_reported,
        "public result.operations.mean_cost_usd",
    )
    if costs_reported == 0:
        if known_cost is not None or operations["observed_cost_usd"] != 0:
            raise BenchmarkError(
                "zero reported costs require null known cost and zero observed cost"
            )
    elif known_cost is None or not math.isclose(
        operations["observed_cost_usd"], known_cost, abs_tol=1e-12
    ):
        raise BenchmarkError("observed cost must equal the sum of known costs")
    if costs_reported == expected_attempts:
        if operations["total_cost_usd"] != known_cost:
            raise BenchmarkError("complete cost telemetry requires total cost equal known cost")
    elif operations["total_cost_usd"] is not None:
        raise BenchmarkError("incomplete cost telemetry requires a null total cost")
    if operations["reviews_with_telemetry"] == expected_attempts:
        if operations["total_elapsed_ms"] != operations["known_elapsed_ms"]:
            raise BenchmarkError("complete elapsed telemetry requires total equal known elapsed")
    elif operations["total_elapsed_ms"] is not None:
        raise BenchmarkError("incomplete elapsed telemetry requires a null total elapsed")
    if release["visibility"] == "public" and (
        provenance["release_git_sha"] != provenance["public_benchmark_git_sha"]
    ):
        raise BenchmarkError("public release Git SHA must equal public benchmark Git SHA")
    if status in _OFFICIAL_STATUSES:
        if release["attempts_per_task"] != 3:
            raise BenchmarkError("official result requires exactly three attempts per task")
        if quality["attempts_scored"] != expected_attempts:
            raise BenchmarkError("official result must score every expected attempt")
        if quality["pending_findings"]:
            raise BenchmarkError("official result cannot contain pending findings")
        if (
            operations["attempt_failures"]
            or operations["attempts_skipped"]
            or operations["cost_guard_triggered"]
        ):
            raise BenchmarkError("official result cannot contain incomplete attempts")
        if operations["reviews_with_telemetry"] != expected_attempts:
            raise BenchmarkError("official result requires telemetry for every attempt")
        if operations["costs_reported"] != expected_attempts:
            raise BenchmarkError("official result requires cost for every attempt")
        if operations["total_cost_usd"] is None or operations["total_elapsed_ms"] is None:
            raise BenchmarkError("official result requires complete cost and elapsed totals")
        if operations["known_cost_usd"] != operations["total_cost_usd"]:
            raise BenchmarkError("official known cost must equal total cost")
        if operations["known_elapsed_ms"] != operations["total_elapsed_ms"]:
            raise BenchmarkError("official known elapsed time must equal total elapsed time")
        if not math.isclose(
            operations["observed_cost_usd"], operations["total_cost_usd"], abs_tol=1e-12
        ):
            raise BenchmarkError("official observed cost must equal total cost")
        if subject["provider"] is None or subject["expected_reported_provider"] is None:
            raise BenchmarkError("official result requires pinned and observed provider identity")
        if not subject["fallbacks_disabled"]:
            raise BenchmarkError("official result requires provider fallbacks disabled")
        if operations["providers"] != [subject["expected_reported_provider"]]:
            raise BenchmarkError("official observed provider does not match the pinned identity")
    return PublicResult(
        record_id=record_id,
        run_id=run_id,
        status=status,
        track=track,
        subject=subject,
        release=release,
        provenance=provenance,
        quality=quality,
        operations=operations,
        raw=payload,
    )


def _parse_registry(value: object) -> tuple[dict[str, Any], ...]:
    payload = _require_dict(value, "result registry")
    _require_keys(payload, "result registry", required={"schema", "records"})
    if payload.get("schema") != RESULT_REGISTRY_SCHEMA:
        raise BenchmarkError(f"result registry.schema must be {RESULT_REGISTRY_SCHEMA!r}")
    records = _require_list(payload.get("records"), "result registry.records")
    parsed: list[dict[str, Any]] = []
    previous: str | None = None
    for index, raw in enumerate(records):
        label = f"result registry.records[{index}]"
        item = _require_dict(raw, label)
        _require_keys(
            item,
            label,
            required={"record_id", "path", "sha256", "supersedes", "reproduces"},
        )
        record_id = _id(item.get("record_id"), f"{label}.record_id")
        if previous is not None and record_id <= previous:
            raise BenchmarkError("result registry records must be unique and sorted by record_id")
        previous = record_id
        expected_path = f"records/{record_id}.json"
        if item.get("path") != expected_path:
            raise BenchmarkError(f"{label}.path must be {expected_path!r}")
        digest = _digest(item.get("sha256"), f"{label}.sha256")
        supersedes_raw = item.get("supersedes")
        supersedes = None if supersedes_raw is None else _id(supersedes_raw, f"{label}.supersedes")
        reproduces_raw = item.get("reproduces")
        reproduces = (
            None
            if reproduces_raw is None
            else _id(reproduces_raw, f"{label}.reproduces")
        )
        if supersedes == record_id:
            raise BenchmarkError(f"{label} cannot supersede itself")
        if reproduces == record_id:
            raise BenchmarkError(f"{label} cannot reproduce itself")
        if supersedes is not None and reproduces is not None:
            raise BenchmarkError(f"{label} cannot both supersede and reproduce")
        parsed.append(
            {
                "record_id": record_id,
                "path": expected_path,
                "sha256": digest,
                "supersedes": supersedes,
                "reproduces": reproduces,
            }
        )
    return tuple(parsed)


def load_result_registry(path: Path) -> ResultRegistry:
    path = Path(path).absolute()
    if _is_reparse(path):
        raise BenchmarkError("result registry must not be a link or reparse point")
    payload = _require_dict(_read_json(path, "result registry"), "result registry")
    parsed = _parse_registry(payload)
    root = path.parent.resolve()
    records_root = root / "records"
    expected_names = {f"{item['record_id']}.json" for item in parsed}
    actual_names: set[str] = set()
    if records_root.exists():
        if not records_root.is_dir() or _is_reparse(records_root):
            raise BenchmarkError("results/records must be a regular directory")
        case_names: dict[str, str] = {}
        for entry in os.scandir(records_root):
            folded = entry.name.casefold()
            if folded in case_names:
                raise BenchmarkError("results/records contains a case collision")
            case_names[folded] = entry.name
            entry_path = Path(entry.path)
            if (
                entry.is_symlink()
                or _is_reparse(entry_path)
                or not entry.is_file(follow_symlinks=False)
            ):
                raise BenchmarkError("results/records contains a non-regular entry")
            actual_names.add(entry.name)
    if actual_names != expected_names:
        raise BenchmarkError("results/records inventory does not exactly match registry")

    records: list[RegistryRecord] = []
    by_id: dict[str, RegistryRecord] = {}
    superseded_by: dict[str, str] = {}
    primary_run_ids: set[str] = set()
    for item in parsed:
        record_path = records_root / f"{item['record_id']}.json"
        try:
            record_bytes = record_path.read_bytes()
        except OSError as exc:
            raise BenchmarkError(f"cannot read result record {item['record_id']!r}") from exc
        if hashlib.sha256(record_bytes).hexdigest() != item["sha256"]:
            raise BenchmarkError(f"registry byte digest mismatch for {item['record_id']}")
        result = load_public_result(record_path)
        if result.record_id != item["record_id"]:
            raise BenchmarkError("registry record ID does not match public result")
        record = RegistryRecord(result=result, **item)
        if result.status in _OFFICIAL_STATUSES:
            if result.run_id in primary_run_ids:
                raise BenchmarkError("one run ID cannot have multiple primary result records")
            primary_run_ids.add(result.run_id)
        records.append(record)
        by_id[record.record_id] = record
    for record in records:
        status = record.result.status
        if status == "official":
            if record.supersedes is not None or record.reproduces is not None:
                raise BenchmarkError("official root records must not declare a relation")
        elif status == "reproduced":
            if record.reproduces is None or record.supersedes is not None:
                raise BenchmarkError("reproduced records require only a reproduces relation")
            parent = by_id.get(record.reproduces)
            if parent is None:
                raise BenchmarkError(
                    f"registry reproduces unknown record {record.reproduces!r}"
                )
            if parent.result.status not in _OFFICIAL_STATUSES:
                raise BenchmarkError("a reproduction must target an official result record")
            if record.result.run_id == parent.result.run_id:
                raise BenchmarkError("a reproduction must have a distinct run ID")
            if (
                record.result.track != parent.result.track
                or record.result.subject != parent.result.subject
                or record.result.release != parent.result.release
            ):
                raise BenchmarkError(
                    "reproduction must retain track, subject, and release identity"
                )
            stable_provenance = {
                "scorer_git_sha",
                "public_benchmark_git_sha",
                "release_git_sha",
                "product_git_sha",
                "release_manifest_sha256",
                "scorer_version",
                "provider_policy",
                "evaluation_config_sha256",
            }
            if any(
                record.result.provenance[field] != parent.result.provenance[field]
                for field in stable_provenance
            ):
                raise BenchmarkError("reproduction changed stable evaluation provenance")
            if (
                record.result.provenance["config_sha256"]
                == parent.result.provenance["config_sha256"]
            ):
                raise BenchmarkError(
                    "a reproduction must have a distinct raw run configuration digest"
                )
        elif status in _DISPOSITION_STATUSES:
            if record.supersedes is None or record.reproduces is not None:
                raise BenchmarkError("disposition records require only a supersedes relation")
            parent = by_id.get(record.supersedes)
            if parent is None:
                raise BenchmarkError(
                    f"registry supersedes unknown record {record.supersedes!r}"
                )
            if record.supersedes in superseded_by:
                raise BenchmarkError("a registry record may have at most one direct superseder")
            superseded_by[record.supersedes] = record.record_id
            identity_fields = (
                record.result.run_id == parent.result.run_id,
                record.result.track == parent.result.track,
                record.result.subject == parent.result.subject,
                record.result.release == parent.result.release,
                record.result.provenance == parent.result.provenance,
            )
            if not all(identity_fields):
                raise BenchmarkError(
                    "disposition must retain exact run/config/release/product/scorer identity"
                )
        else:
            raise BenchmarkError(
                "registry may contain only official, reproduced, or disposition records"
            )
    for record in records:
        seen: set[str] = set()
        current = record
        while (parent_id := current.supersedes or current.reproduces) is not None:
            if current.record_id in seen:
                raise BenchmarkError("registry relation graph contains a cycle")
            seen.add(current.record_id)
            current = by_id[parent_id]
    return ResultRegistry(root=root, records=tuple(records), raw=payload)


def validate_registry_against_git_base(path: Path, base_ref: str) -> None:
    """Reject modification/deletion of any registry entry or record in a Git base."""

    current = load_result_registry(path)
    try:
        repo = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise BenchmarkError("result registry is not inside a Git worktree") from exc
    repo_root = Path(repo).resolve()
    registry_relative = path.resolve().relative_to(repo_root).as_posix()

    def git_show(relative: str) -> bytes | None:
        process = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{base_ref}:{relative}"],
            check=False,
            capture_output=True,
        )
        if process.returncode == 0:
            return process.stdout
        exists = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{base_ref}^{{commit}}"],
            check=False,
            capture_output=True,
        )
        if exists.returncode:
            raise BenchmarkError(f"cannot resolve Git base ref {base_ref!r}")
        return None

    base_bytes = git_show(registry_relative)
    if base_bytes is None:
        return
    try:
        base_payload = _json_loads(base_bytes, "base result registry")
    except BenchmarkError as exc:
        raise BenchmarkError("base result registry is invalid JSON") from exc
    base_entries = {item["record_id"]: item for item in _parse_registry(base_payload)}
    current_entries = {
        record.record_id: {
            "record_id": record.record_id,
            "path": record.path,
            "sha256": record.sha256,
            "supersedes": record.supersedes,
            "reproduces": record.reproduces,
        }
        for record in current.records
    }
    for record_id, base_entry in base_entries.items():
        if current_entries.get(record_id) != base_entry:
            raise BenchmarkError(f"existing registry entry {record_id!r} was modified or deleted")
        base_record_path = (Path(registry_relative).parent / base_entry["path"]).as_posix()
        original = git_show(base_record_path)
        if original is None:
            raise BenchmarkError(f"base record {record_id!r} is missing or inconsistent")
        if hashlib.sha256(original).hexdigest() != base_entry["sha256"]:
            raise BenchmarkError(f"base record {record_id!r} is missing or inconsistent")
        current_bytes = (current.root / base_entry["path"]).read_bytes()
        if current_bytes != original:
            raise BenchmarkError(f"existing result record {record_id!r} was modified")
