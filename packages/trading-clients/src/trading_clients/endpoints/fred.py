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
class GetReleasesRequest(ParamsRequest):
    limit: int = 20

    def to_params(self) -> dict[str, str]:
        return {
            "limit": str(self.limit),
            "include_release_dates_with_no_data": "true",
            "sort_order": "asc",
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
        return ", ".join(
            f"{o.get('date', '')}: {o.get('value', '')}" for o in self.observations
        )


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
class ReleasesResponse:
    releases: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "ReleasesResponse":
        return cls(releases=data or [])

    def to_output(self) -> str:
        if not self.releases:
            return "(no releases)"
        return ", ".join(
            f"{r.get('date', '')} {r.get('release_name', '')}" for r in self.releases
        )


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

RELEASES = Endpoint(
    "/releases/dates",
    cache_ttl=3600,
    response_model=ReleasesResponse,
    extract=lambda d: d.get("release_dates", []),
)

SEARCH = Endpoint(
    "/series/search",
    cache_ttl=3600,
    response_model=FredSearchResponse,
    extract=lambda d: d.get("seriess", []),
)
