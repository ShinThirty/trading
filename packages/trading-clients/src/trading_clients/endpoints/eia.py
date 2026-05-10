"""EIA Open Data API endpoint definitions.

The EIA v2 API exposes time series via path-based queries (faceted) and a
simpler convenience endpoint at /seriesid/{series_id} that returns the raw
data for a single series. We use the latter — every EIA series we care about
(Weekly Petroleum Status Report stocks, refinery utilization, retail gasoline,
etc.) has a stable series ID, and one ID per request keeps the response shape
flat and parseable.

Series IDs are intentionally NOT enumerated in this file — the tool layer
(tools/eia.py) curates which WPSR series matter for the trading workflow.
This file just provides the shared request/response plumbing.
"""

from dataclasses import dataclass, field
from typing import Any

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest


@dataclass
class EiaSeriesRequest(PathRequest, ParamsRequest):
    """Fetch a single EIA series by ID, newest first.

    series_id: e.g. 'WCESTUS1' (weekly U.S. crude stocks ex SPR).
    length: number of observations to return (default 20 — enough for
      WoW + 8w trend + a buffer).
    """

    series_id: str
    length: int = 20

    def to_path_params(self) -> dict[str, str]:
        return {"series_id": self.series_id}

    def to_params(self) -> dict[str, str]:
        # EIA v2 supports sort[N][column] / sort[N][direction] for explicit
        # ordering. Newest-first matches every other time-series client we
        # have (FRED, CFTC) so callers can index [0] for the latest point.
        return {
            "length": str(self.length),
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        }


@dataclass
class EiaPoint:
    period: str  # YYYY-MM-DD (or YYYY-MM, YYYY-Qn etc. depending on frequency)
    value: float | None


@dataclass
class EiaSeriesResponse:
    """Decoded EIA single-series response.

    EIA returns values as strings (sometimes ints, sometimes floats); we coerce
    once at parse time so the tool layer can stay numeric.
    """

    series_id: str
    units: str | None
    frequency: str | None
    data: list[EiaPoint] = field(default_factory=list)

    @classmethod
    def from_response(cls, raw: Any) -> "EiaSeriesResponse":
        # The /seriesid endpoint wraps payload under {"response": {...}}.
        # extract= isn't useful here because we want the surrounding metadata
        # too (units, frequency), not just the data array.
        resp = (raw or {}).get("response", {}) or {}
        data_rows = resp.get("data") or []
        # Series ID is echoed inside each row but it's redundant; pull it from
        # the first row when available so the response is self-describing even
        # if the caller didn't keep the request.
        series_id = ""
        units: str | None = None
        if data_rows:
            first = data_rows[0]
            series_id = str(first.get("series", "") or first.get("seriesId", ""))
            units = first.get("units") or first.get("unit") or None
        points: list[EiaPoint] = []
        for row in data_rows:
            period = str(row.get("period", "")).strip()
            raw_value = row.get("value")
            value: float | None
            if raw_value is None or raw_value == "":
                value = None
            else:
                try:
                    value = float(raw_value)
                except (ValueError, TypeError):
                    value = None
            if period:
                points.append(EiaPoint(period=period, value=value))
        return cls(
            series_id=series_id,
            units=units,
            frequency=resp.get("frequency"),
            data=points,
        )

    def to_output(self) -> str:
        # Inline format mirrors FRED ObservationsResponse — comma-separated
        # period:value pairs. This is fallback rendering; the EIA tool builds
        # its own multi-series tables.
        if not self.data:
            return f"({self.series_id or 'EIA series'}: no data)"
        parts = [f"{p.period}: {p.value}" for p in self.data if p.value is not None]
        return ", ".join(parts) if parts else f"({self.series_id}: all values null)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# 1h cache — WPSR publishes Wednesday 10:30 ET; intraday changes are nil.
# Same TTL as FRED OBSERVATIONS for consistency.
SERIES = Endpoint(
    "/seriesid/{series_id}",
    cache_ttl=3600,
    response_model=EiaSeriesResponse,
    base_url="https://api.eia.gov/v2",
)
