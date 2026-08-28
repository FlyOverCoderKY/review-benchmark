import pytest
from calc import apply_cap, average_contribution, contribution_total
from report import annual_report
from rules import CAPS, SUPPORTED_YEARS


def test_2026_cap() -> None:
    assert apply_cap(9_000, 2026) == 8_300


def test_2027_cap() -> None:
    assert apply_cap(9_000, 2027) == 8_550


def test_default_year_remains_2026() -> None:
    assert apply_cap(9_000) == 8_300


def test_cap_preserves_below_cap_and_boundary_amounts() -> None:
    assert apply_cap(8_000, 2026) == 8_000
    assert apply_cap(8_300, 2026) == 8_300


def test_apply_cap_rejects_unsupported_year() -> None:
    with pytest.raises(KeyError, match="2028"):
        apply_cap(9_000, 2028)


def test_registry_is_derived_from_cap_table() -> None:
    assert SUPPORTED_YEARS == tuple(CAPS) == (2026, 2027)


def test_average_preserves_fractional_result() -> None:
    assert average_contribution([100, 301]) == 200.5


def test_average_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        average_contribution([])


def test_negative_amount() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        contribution_total([100, -1])


def test_average_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        average_contribution([100, -1])


def test_2026_report() -> None:
    assert annual_report([9_000], 2026) == {"year": 2026, "capped_total": 8_300}


def test_2027_report() -> None:
    assert annual_report([9_000], 2027) == {"year": 2027, "capped_total": 8_550}


def test_report_rejects_unsupported_year() -> None:
    with pytest.raises(KeyError, match="2028"):
        annual_report([9_000], 2028)
