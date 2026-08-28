"""Contribution calculations for a small benefits service."""

CAPS = {2026: 8_300, 2027: 8_300}


def apply_cap(amount: int, year: int = 2026) -> int:
    return min(amount, CAPS[year])


def contribution_total(amounts: list[int]) -> int:
    return sum(amounts)


def average_contribution(amounts: list[int]) -> float:
    return contribution_total(amounts) / len(amounts)
