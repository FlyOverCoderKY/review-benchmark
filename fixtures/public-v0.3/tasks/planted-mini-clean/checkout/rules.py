"""The independently maintained plan-year registry."""

CAPS = {2026: 8_300, 2027: 8_550}

# Backward-compatible registry view, derived from the canonical cap table.
SUPPORTED_YEARS = tuple(CAPS)
