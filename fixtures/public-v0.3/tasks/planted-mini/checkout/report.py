"""Annual report assembly."""

from calc import apply_cap, contribution_total


def annual_report(amounts: list[int], year: int) -> dict[str, int]:
    capped = apply_cap(contribution_total(amounts))
    return {"year": year, "capped_total": capped}
