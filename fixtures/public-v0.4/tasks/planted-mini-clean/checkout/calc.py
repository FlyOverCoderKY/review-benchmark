"""Contribution calculations for a small benefits service."""

from rules import CAPS


def apply_cap(amount: int, year: int = 2026) -> int:
    """Apply a plan-year cap; the 2026 default is retained for compatibility."""
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
