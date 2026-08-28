"""Public contracts and deterministic scoring for review-benchmark."""

from review_benchmark.models import (
    Adjudication,
    BenchmarkError,
    Finding,
    GoldFinding,
    Task,
    load_task,
)
from review_benchmark.scoring import Score, score_findings

__all__ = [
    "Adjudication",
    "BenchmarkError",
    "Finding",
    "GoldFinding",
    "Score",
    "Task",
    "load_task",
    "score_findings",
]

__version__ = "0.1.0"
