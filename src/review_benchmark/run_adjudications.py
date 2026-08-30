"""Neutral, immutable bindings for two-human run adjudication overlays."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review_benchmark.models import (
    BenchmarkError,
    _read_json,
    _require_dict,
    _require_keys,
    _require_list,
    _require_str,
)
from review_benchmark.release import _is_reparse

RUN_ADJUDICATIONS_SCHEMA = "review-benchmark/run-adjudications/1"
PENDING_FINDING_ID_SCHEMA = "review-benchmark/pending-finding-id/1"
REVIEW_RESPONSE_SCHEMA = "review-benchmark/adjudication-review-response/1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
_VERDICTS = {
    "valid_extra",
    "false_positive",
    "oracle_gap",
    "insufficient_evidence",
}
_RESOLUTIONS = {*_VERDICTS, "disagreement"}
_PUBLISHABLE_RESOLUTIONS = {"valid_extra", "false_positive"}
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _bounded_string(value: object, label: str, maximum: int = 200) -> str:
    result = _require_str(value, label)
    if len(result) > maximum:
        raise BenchmarkError(f"{label} must contain at most {maximum} characters")
    return result


def _finding_index(value: object, label: str) -> int:
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


def canonical_json_bytes(value: object) -> bytes:
    """Encode one JSON value using the benchmark's canonical digest form."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BenchmarkError("value cannot be represented as canonical JSON") from exc


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def derive_finding_sha256(finding: object) -> str:
    """Digest the normalized finding object used by one immutable attempt."""

    if not isinstance(finding, dict):
        raise BenchmarkError("normalized finding must be a JSON object")
    return canonical_sha256(finding)


def derive_finding_id(
    *,
    run_id: str,
    task_id: str,
    attempt_id: str,
    normalized_attempt_sha256: str,
    finding_index: int,
    finding_sha256: str,
) -> str:
    """Derive the opaque ID from the complete normalized finding origin."""

    _bounded_string(run_id, "finding ID run_id")
    _bounded_string(task_id, "finding ID task_id")
    _bounded_string(attempt_id, "finding ID attempt_id")
    _sha256(normalized_attempt_sha256, "finding ID normalized_attempt_sha256")
    _sha256(finding_sha256, "finding ID finding_sha256")
    finding_index = _finding_index(finding_index, "finding ID finding_index")
    return canonical_sha256(
        {
            "schema": PENDING_FINDING_ID_SCHEMA,
            "run_id": run_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "normalized_attempt_sha256": normalized_attempt_sha256,
            "finding_index": finding_index,
            "finding_sha256": finding_sha256,
        }
    )


def reviewer_response_sha256(
    *, finding_id: str, reviewer_id: str, verdict: str, reason: str
) -> str:
    """Bind one reviewer identity and exact response content."""

    _sha256(finding_id, "review response finding_id")
    _identifier(reviewer_id, "review response reviewer_id")
    if verdict not in _VERDICTS:
        raise BenchmarkError("review response verdict is invalid")
    _require_str(reason, "review response reason")
    return canonical_sha256(
        {
            "schema": REVIEW_RESPONSE_SCHEMA,
            "finding_id": finding_id,
            "reviewer_id": reviewer_id,
            "verdict": verdict,
            "reason": reason,
        }
    )


def _sha256(value: object, label: str) -> str:
    digest = _require_str(value, label)
    if _SHA256_RE.fullmatch(digest) is None:
        raise BenchmarkError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _identifier(value: object, label: str) -> str:
    identifier = _require_str(value, label)
    if _ID_RE.fullmatch(identifier) is None:
        raise BenchmarkError(f"{label} must be a normalized identifier")
    return identifier


def _git_sha(value: object, label: str) -> str:
    digest = _require_str(value, label)
    if _GIT_SHA_RE.fullmatch(digest) is None:
        raise BenchmarkError(f"{label} must be a lowercase 40-character Git SHA")
    return digest


@dataclass(frozen=True, order=True)
class PendingFindingBinding:
    finding_id: str
    task_id: str
    attempt_id: str
    normalized_attempt_sha256: str
    finding_index: int
    finding_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.finding_id, "pending finding_id")
        _bounded_string(self.task_id, "pending task_id")
        _bounded_string(self.attempt_id, "pending attempt_id")
        _sha256(self.normalized_attempt_sha256, "pending normalized_attempt_sha256")
        object.__setattr__(
            self,
            "finding_index",
            _finding_index(self.finding_index, "pending finding_index"),
        )
        _sha256(self.finding_sha256, "pending finding_sha256")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "finding_id": self.finding_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "normalized_attempt_sha256": self.normalized_attempt_sha256,
            "finding_index": self.finding_index,
            "finding_sha256": self.finding_sha256,
        }


@dataclass(frozen=True)
class RunAdjudicationBinding:
    run_id: str
    manifest_sha256: str
    private_score_sha256: str
    config_sha256: str
    release_id: str
    release_git_sha: str
    release_manifest_sha256: str
    scorer_git_sha: str
    scorer_version: str
    pending: tuple[PendingFindingBinding, ...]

    def __post_init__(self) -> None:
        _bounded_string(self.run_id, "binding.run_id")
        _sha256(self.manifest_sha256, "binding.manifest_sha256")
        _sha256(self.private_score_sha256, "binding.private_score_sha256")
        _sha256(self.config_sha256, "binding.config_sha256")
        _bounded_string(self.release_id, "binding.release_id")
        _git_sha(self.release_git_sha, "binding.release_git_sha")
        _sha256(self.release_manifest_sha256, "binding.release_manifest_sha256")
        _git_sha(self.scorer_git_sha, "binding.scorer_git_sha")
        _bounded_string(self.scorer_version, "binding.scorer_version")
        if tuple(sorted(self.pending)) != self.pending:
            raise BenchmarkError("binding.pending must be sorted by finding_id")
        ids = [item.finding_id for item in self.pending]
        if len(ids) != len(set(ids)):
            raise BenchmarkError("binding.pending contains duplicate finding IDs")


@dataclass(frozen=True)
class RunAdjudications:
    adjudication_id: str
    binding: RunAdjudicationBinding
    reviewers: tuple[str, str]
    resolutions: tuple[tuple[str, str], ...]
    document_sha256: str
    raw: dict[str, Any]


def pending_set_sha256(pending: tuple[PendingFindingBinding, ...]) -> str:
    if tuple(sorted(pending)) != pending:
        raise BenchmarkError("pending findings must be sorted by finding_id")
    ids = [item.finding_id for item in pending]
    if len(ids) != len(set(ids)):
        raise BenchmarkError("pending findings contain duplicate finding IDs")
    return canonical_sha256([item.to_dict() for item in pending])


def document_sha256(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("document_sha256", None)
    return canonical_sha256(unsigned)


def _run_binding(
    value: object, pending: tuple[PendingFindingBinding, ...]
) -> RunAdjudicationBinding:
    run = _require_dict(value, "run adjudications.run")
    _require_keys(
        run,
        "run adjudications.run",
        required={
            "run_id",
            "manifest_sha256",
            "private_score_sha256",
            "config_sha256",
            "release_id",
            "release_git_sha",
            "release_manifest_sha256",
            "scorer_git_sha",
            "scorer_version",
        },
    )
    return RunAdjudicationBinding(
        run_id=_bounded_string(run.get("run_id"), "run adjudications.run.run_id"),
        manifest_sha256=_sha256(
            run.get("manifest_sha256"), "run adjudications.run.manifest_sha256"
        ),
        private_score_sha256=_sha256(
            run.get("private_score_sha256"),
            "run adjudications.run.private_score_sha256",
        ),
        config_sha256=_sha256(
            run.get("config_sha256"), "run adjudications.run.config_sha256"
        ),
        release_id=_bounded_string(
            run.get("release_id"), "run adjudications.run.release_id"
        ),
        release_git_sha=_git_sha(
            run.get("release_git_sha"), "run adjudications.run.release_git_sha"
        ),
        release_manifest_sha256=_sha256(
            run.get("release_manifest_sha256"),
            "run adjudications.run.release_manifest_sha256",
        ),
        scorer_git_sha=_git_sha(
            run.get("scorer_git_sha"), "run adjudications.run.scorer_git_sha"
        ),
        scorer_version=_bounded_string(
            run.get("scorer_version"), "run adjudications.run.scorer_version"
        ),
        pending=pending,
    )


def load_run_adjudications(
    path: Path,
    *,
    expected: RunAdjudicationBinding | None = None,
    require_resolved: bool = False,
) -> RunAdjudications:
    """Load a sealed overlay and optionally bind it to an exact run/pending set."""

    path = Path(path).absolute()
    if _is_reparse(path):
        raise BenchmarkError("run adjudications must not be a link or reparse point")
    payload = _require_dict(_read_json(path, "run adjudications"), "run adjudications")
    _require_keys(
        payload,
        "run adjudications",
        required={
            "schema",
            "adjudication_id",
            "status",
            "run",
            "pending_set_sha256",
            "reviewers",
            "decisions",
            "document_sha256",
        },
    )
    if payload.get("schema") != RUN_ADJUDICATIONS_SCHEMA:
        raise BenchmarkError(
            f"run adjudications.schema must be {RUN_ADJUDICATIONS_SCHEMA!r}"
        )
    if payload.get("status") != "complete":
        raise BenchmarkError("run adjudications.status must be 'complete'")
    adjudication_id = _identifier(
        payload.get("adjudication_id"), "run adjudications.adjudication_id"
    )
    actual_document_sha = _sha256(
        payload.get("document_sha256"), "run adjudications.document_sha256"
    )
    if actual_document_sha != document_sha256(payload):
        raise BenchmarkError("run adjudications.document_sha256 does not match document")
    reviewer_values = _require_list(payload.get("reviewers"), "run adjudications.reviewers")
    if len(reviewer_values) != 2:
        raise BenchmarkError("run adjudications.reviewers must contain exactly two entries")
    reviewers = tuple(
        _identifier(value, f"run adjudications.reviewers[{index}]")
        for index, value in enumerate(reviewer_values)
    )
    if reviewers[0] >= reviewers[1]:
        raise BenchmarkError(
            "run adjudications.reviewers must be distinct and lexicographically sorted"
        )

    decisions = _require_list(payload.get("decisions"), "run adjudications.decisions")
    if len(decisions) > 100_000:
        raise BenchmarkError("run adjudications.decisions must contain at most 100000 entries")
    pending: list[PendingFindingBinding] = []
    resolutions: list[tuple[str, str]] = []
    origins: set[tuple[str, str, int]] = set()
    attempt_digests: dict[tuple[str, str], str] = {}
    previous_id: str | None = None
    for index, value in enumerate(decisions):
        label = f"run adjudications.decisions[{index}]"
        decision = _require_dict(value, label)
        _require_keys(
            decision,
            label,
            required={"finding", "reviews", "resolution"},
        )
        finding = _require_dict(decision.get("finding"), f"{label}.finding")
        _require_keys(
            finding,
            f"{label}.finding",
            required={
                "finding_id",
                "task_id",
                "attempt_id",
                "normalized_attempt_sha256",
                "finding_index",
                "finding_sha256",
            },
        )
        finding_id = _sha256(finding.get("finding_id"), f"{label}.finding.finding_id")
        finding_sha = _sha256(
            finding.get("finding_sha256"), f"{label}.finding.finding_sha256"
        )
        if previous_id is not None and finding_id <= previous_id:
            raise BenchmarkError(
                "run adjudications.decisions must be unique and sorted by finding_id"
            )
        previous_id = finding_id
        reviews = _require_list(decision.get("reviews"), f"{label}.reviews")
        if len(reviews) != 2:
            raise BenchmarkError(f"{label}.reviews must contain exactly two entries")
        verdicts: list[str] = []
        for review_index, review_value in enumerate(reviews):
            review_label = f"{label}.reviews[{review_index}]"
            review = _require_dict(review_value, review_label)
            _require_keys(
                review,
                review_label,
                required={"reviewer_id", "verdict", "reason", "response_sha256"},
            )
            if review.get("reviewer_id") != reviewers[review_index]:
                raise BenchmarkError(f"{review_label}.reviewer_id does not match reviewer roster")
            verdict = _require_str(review.get("verdict"), f"{review_label}.verdict")
            if verdict not in _VERDICTS:
                raise BenchmarkError(f"{review_label}.verdict is invalid")
            reason = _require_str(review.get("reason"), f"{review_label}.reason")
            if len(reason) > 4000:
                raise BenchmarkError(f"{review_label}.reason is too long")
            response_digest = _sha256(
                review.get("response_sha256"), f"{review_label}.response_sha256"
            )
            if response_digest != reviewer_response_sha256(
                finding_id=finding_id,
                reviewer_id=reviewers[review_index],
                verdict=verdict,
                reason=reason,
            ):
                raise BenchmarkError(f"{review_label}.response_sha256 does not match response")
            verdicts.append(verdict)
        derived = verdicts[0] if verdicts[0] == verdicts[1] else "disagreement"
        resolution = _require_str(decision.get("resolution"), f"{label}.resolution")
        if resolution not in _RESOLUTIONS or resolution != derived:
            raise BenchmarkError(f"{label}.resolution does not match the two reviews")
        if require_resolved and resolution not in _PUBLISHABLE_RESOLUTIONS:
            raise BenchmarkError(
                f"run adjudications contain publication-blocking resolution {resolution!r}"
            )
        finding_index = _finding_index(
            finding.get("finding_index"), f"{label}.finding.finding_index"
        )
        task_id = _bounded_string(finding.get("task_id"), f"{label}.finding.task_id")
        attempt_id = _bounded_string(
            finding.get("attempt_id"), f"{label}.finding.attempt_id"
        )
        normalized_attempt_sha = _sha256(
            finding.get("normalized_attempt_sha256"),
            f"{label}.finding.normalized_attempt_sha256",
        )
        origin = (task_id, attempt_id, finding_index)
        if origin in origins:
            raise BenchmarkError("run adjudications contain a duplicate finding origin")
        origins.add(origin)
        attempt_key = (task_id, attempt_id)
        previous_attempt_sha = attempt_digests.setdefault(
            attempt_key, normalized_attempt_sha
        )
        if previous_attempt_sha != normalized_attempt_sha:
            raise BenchmarkError("one normalized attempt identity has conflicting digests")
        pending.append(
            PendingFindingBinding(
                finding_id=finding_id,
                task_id=task_id,
                attempt_id=attempt_id,
                normalized_attempt_sha256=normalized_attempt_sha,
                finding_index=finding_index,
                finding_sha256=finding_sha,
            )
        )
        if finding_id != derive_finding_id(
            run_id=_require_dict(
                payload.get("run"), "run adjudications.run"
            ).get("run_id"),
            task_id=task_id,
            attempt_id=attempt_id,
            normalized_attempt_sha256=normalized_attempt_sha,
            finding_index=finding_index,
            finding_sha256=finding_sha,
        ):
            raise BenchmarkError(f"{label}.finding.finding_id is not canonically derived")
        resolutions.append((finding_id, resolution))

    pending_tuple = tuple(pending)
    binding = _run_binding(payload.get("run"), pending_tuple)
    expected_pending_sha = pending_set_sha256(pending_tuple)
    actual_pending_sha = _sha256(
        payload.get("pending_set_sha256"), "run adjudications.pending_set_sha256"
    )
    if actual_pending_sha != expected_pending_sha:
        raise BenchmarkError("run adjudications.pending_set_sha256 does not match decisions")
    if expected is not None and binding != expected:
        raise BenchmarkError("run adjudications do not match the expected immutable run binding")
    return RunAdjudications(
        adjudication_id=adjudication_id,
        binding=binding,
        reviewers=(reviewers[0], reviewers[1]),
        resolutions=tuple(resolutions),
        document_sha256=actual_document_sha,
        raw=payload,
    )
