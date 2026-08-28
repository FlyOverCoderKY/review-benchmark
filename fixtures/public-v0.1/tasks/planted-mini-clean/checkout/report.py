"""Annual report assembly."""

from calc import apply_cap, contribution_total
from rules import SUPPORTED_YEARS


def annual_report(amounts: list[int], year: int) -> dict[str, int]:
    if year not in SUPPORTED_YEARS:
        raise ValueError(f"unsupported year {year}")
    capped = apply_cap(contribution_total(amounts), year)
    return {"year": year, "capped_total": capped}
