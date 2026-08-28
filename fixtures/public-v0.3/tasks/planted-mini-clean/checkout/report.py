"""Annual report assembly."""

from calc import apply_cap, contribution_total


def annual_report(amounts: list[int], year: int) -> dict[str, int]:
    total = contribution_total(amounts)
    capped = apply_cap(total, year)
    return {"year": year, "capped_total": capped}
