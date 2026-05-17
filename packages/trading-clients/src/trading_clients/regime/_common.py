"""Shared internal helpers for the regime package."""


def parse_fred_value(observations: list[dict]) -> tuple[float | None, str]:
    """Extract the latest numeric value from FRED observations.

    FRED returns values as strings; '.' means data unavailable.
    Returns (value, date) tuple.
    """
    if not observations:
        return None, ""
    obs = observations[0]
    date = obs.get("date", "")
    val = obs.get("value", ".")
    if val == ".":
        return None, date
    try:
        return float(val), date
    except (ValueError, TypeError):
        return None, date


def _pct_return(closes: list[float], lookback: int) -> float | None:
    """Compute percentage return over a lookback period (trading days)."""
    if len(closes) < lookback + 1:
        return None
    return (closes[-1] - closes[-1 - lookback]) / closes[-1 - lookback] * 100


def _fed_direction(fed_funds: float | None, prev_fed_funds: float | None) -> str:
    """Determine Fed funds direction from two consecutive observations."""
    if fed_funds is None or prev_fed_funds is None:
        return "unknown"
    if fed_funds > prev_fed_funds:
        return "rising"
    if fed_funds < prev_fed_funds:
        return "falling"
    return "stable"
