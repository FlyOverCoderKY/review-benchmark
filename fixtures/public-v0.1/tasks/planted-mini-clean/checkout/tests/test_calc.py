from calc import apply_cap, average_contribution, contribution_total
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
