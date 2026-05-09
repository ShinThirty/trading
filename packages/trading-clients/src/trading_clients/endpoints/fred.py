"""FRED API endpoint definitions with typed request/response models."""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.table_helpers import kv_table, list_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class GetObservationsRequest(ParamsRequest):
    series_id: str
    limit: int = 12
    sort_order: str = "desc"

    def to_params(self) -> dict[str, str]:
        return {
            "series_id": self.series_id,
            "limit": str(self.limit),
            "sort_order": self.sort_order,
        }


@dataclass
class SeriesIdRequest(ParamsRequest):
    series_id: str

    def to_params(self) -> dict[str, str]:
        return {"series_id": self.series_id}


@dataclass
class GetReleaseDatesRequest(ParamsRequest):
    release_id: int
    realtime_start: str | None = None
    realtime_end: str | None = None

    def to_params(self) -> dict[str, str]:
        params = {
            "release_id": str(self.release_id),
            "include_release_dates_with_no_data": "true",
            "sort_order": "asc",
        }
        if self.realtime_start:
            params["realtime_start"] = self.realtime_start
        if self.realtime_end:
            params["realtime_end"] = self.realtime_end
        return params


# Curated FRED release IDs surfaced to the briefing skill, tagged by what the
# print measures rather than a judgment of impact.
# FOMC is intentionally excluded — FRED release_id 101 ("FOMC Press Release") is
# a daily-update feed, not a meeting calendar. Use FOMC_CALENDAR (fed.gov scrape)
# and get_fomc_decision_texture for FOMC days instead.
# Daily/weekly market noise (SOFR, Coinbase, Dow Jones, etc.) is also excluded.
MACRO_RELEASES: dict[int, tuple[str, str]] = {
    # Labor
    50: ("Labor", "Employment Situation (NFP)"),
    192: ("Labor", "JOLTS"),
    194: ("Labor", "ADP Employment"),
    180: ("Labor", "Initial Jobless Claims"),
    # Inflation
    10: ("Inflation", "CPI"),
    54: ("Inflation", "Personal Income and Outlays (PCE)"),
    46: ("Inflation", "PPI"),
    # Activity
    9: ("Activity", "Retail Sales"),
    13: ("Activity", "Industrial Production"),
    95: ("Activity", "Durable Goods"),
    # Housing
    27: ("Housing", "Housing Starts/Permits"),
    97: ("Housing", "New Home Sales"),
    291: ("Housing", "Existing Home Sales"),
    # Trade
    51: ("Trade", "International Trade"),
    # Growth
    53: ("Growth", "GDP"),
}


@dataclass
class SearchRequest(ParamsRequest):
    search_text: str
    limit: int = 10

    def to_params(self) -> dict[str, str]:
        return {"search_text": self.search_text, "limit": str(self.limit)}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class ObservationsResponse:
    observations: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "ObservationsResponse":
        return cls(observations=data or [])

    def to_output(self) -> str:
        if not self.observations:
            return "(no data)"
        return ", ".join(f"{o.get('date', '')}: {o.get('value', '')}" for o in self.observations)


@dataclass
class SeriesInfoResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "SeriesInfoResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        if not self.data:
            return "(no data)"
        return kv_table(
            {
                "ID": self.data.get("id"),
                "Title": self.data.get("title"),
                "Frequency": self.data.get("frequency"),
                "Units": self.data.get("units"),
                "Seasonal Adj": self.data.get("seasonal_adjustment"),
                "Last Updated": self.data.get("last_updated"),
            }
        )


@dataclass
class ReleaseDatesResponse:
    dates: list[str]

    @classmethod
    def from_response(cls, data: list[dict]) -> "ReleaseDatesResponse":
        return cls(dates=[d.get("date", "") for d in (data or []) if d.get("date")])

    def to_output(self) -> str:
        return ", ".join(self.dates) if self.dates else "(no dates)"


@dataclass
class FredSearchResponse:
    series: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "FredSearchResponse":
        return cls(series=data or [])

    def to_output(self) -> str:
        if not self.series:
            return "(no results)"
        rows = [
            {
                "ID": s.get("id", ""),
                "Title": s.get("title", ""),
                "Frequency": s.get("frequency", ""),
                "Units": s.get("units", ""),
            }
            for s in self.series
        ]
        return list_table(rows)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

OBSERVATIONS = Endpoint(
    "/series/observations",
    cache_ttl=3600,
    response_model=ObservationsResponse,
    extract=lambda d: d.get("observations", []),
)

SERIES_INFO = Endpoint(
    "/series",
    cache_ttl=3600,
    response_model=SeriesInfoResponse,
    extract=lambda d: d.get("seriess", [{}])[0],
)

RELEASE_DATES = Endpoint(
    "/release/dates",
    cache_ttl=3600,
    response_model=ReleaseDatesResponse,
    extract=lambda d: d.get("release_dates", []),
)

SEARCH = Endpoint(
    "/series/search",
    cache_ttl=3600,
    response_model=FredSearchResponse,
    extract=lambda d: d.get("seriess", []),
)
