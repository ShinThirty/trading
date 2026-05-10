"""Container-freight signals: Freightos Baltic Index (FBX) lane prices +
IMF PortWatch daily chokepoint transit volumes.

Used to confirm geopolitical-risk rerouting. Canonical pattern: a Red Sea
disruption shows up as FBX China-N Europe + China-Med spiking, Bab el-
Mandeb transits collapsing, and Cape of Good Hope transits surging within
the same week — all three required to call it a real reroute, not just a
freight rate noise spike.

Two providers consumed by one tool:
- **Freightos** publishes the FBX. Each lane has a /enterprise/terminal/<slug>/
  page that embeds the weekly history as a JSON array inside the HTML. We
  regex-extract the array (no JS needed).
- **IMF PortWatch** publishes daily chokepoint vessel counts via ArcGIS
  REST. The Daily_Chokepoints_Data layer has 28 chokepoints; we query the
  7 with the highest trade-route relevance.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest

# ═══════════════════════════════════════════════════════════════
# Freightos Baltic Index (FBX) — lane price scraper
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FbxLane:
    """FBX lane catalog entry. `slug` is the URL fragment under
    /enterprise/terminal/; `ticker` is the identifier the page embeds in
    its JSON series."""

    ticker: str
    slug: str
    label: str


FBX_GLOBAL = FbxLane(
    ticker="FBX",
    slug="freightos-baltic-index-global-container-pricing-index",
    label="Global",
)

# Four high-signal Asia↔Western lanes. Together they triangulate the two
# main chokepoint scenarios: Panama-routed (FBX01 China-NAmWC), and the
# Suez-routed cluster (FBX03 China-NAmEC, FBX11 China-N Europe, FBX13
# China-Med). FBX13 reacts hardest to Red Sea disruption since the Med
# routing is most Suez-dependent.
FBX_LANES: dict[str, FbxLane] = {
    "FBX01": FbxLane("FBX01", "fbx-01-china-to-north-america-west-coast", "China → NAm WC"),
    "FBX03": FbxLane("FBX03", "fbx-03-china-to-north-america-east-coast", "China → NAm EC"),
    "FBX11": FbxLane("FBX11", "fbx-11-china-to-northern-europe", "China → N Europe"),
    "FBX13": FbxLane("FBX13", "fbx-13-china-to-mediterranean", "China → Med"),
}

# Embedded series objects in page HTML look like:
#   {"ticker":"FBX01","indexDate":"2026-05-08","value":2345.6}
_FBX_TICK_RE = re.compile(
    r'\{"ticker":"(?P<ticker>FBX[0-9]*)",'
    r'"indexDate":"(?P<date>\d{4}-\d{2}-\d{2})",'
    r'"value":(?P<value>\d+(?:\.\d+)?)\}'
)


@dataclass
class FreightosLanePathRequest(PathRequest, ParamsRequest):
    """Fetch a Freightos terminal page by slug."""

    slug: str

    def to_path_params(self) -> dict[str, str]:
        return {"slug": self.slug}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class FreightosPageResponse:
    """Parsed FBX series per ticker found in the page HTML.

    Each route page typically embeds only its own ticker (~52 weekly
    points), but the structure is per-ticker so callers can pull
    whichever ones they find. Series are date-ascending; [-1] is latest.
    """

    series: dict[str, list[tuple[str, float]]] = field(default_factory=dict)

    @classmethod
    def from_response(cls, html: str) -> "FreightosPageResponse":
        if not html:
            return cls()
        bucket: dict[str, list[tuple[str, float]]] = {}
        for m in _FBX_TICK_RE.finditer(html):
            t = m.group("ticker")
            bucket.setdefault(t, []).append((m.group("date"), float(m.group("value"))))
        for t in bucket:
            bucket[t].sort(key=lambda r: r[0])
        return cls(series=bucket)

    def latest_for(self, ticker: str) -> tuple[str, float] | None:
        s = self.series.get(ticker)
        return s[-1] if s else None

    def history_for(self, ticker: str) -> list[tuple[str, float]]:
        return self.series.get(ticker, [])

    def to_output(self) -> str:
        if not self.series:
            return "(no FBX series parsed)"
        parts = []
        for t, s in sorted(self.series.items()):
            if s:
                parts.append(f"{t}={s[-1][1]:.1f} ({s[-1][0]})")
        return "; ".join(parts)


FREIGHTOS_FBX_PAGE = Endpoint(
    "/enterprise/terminal/{slug}/",
    cache_ttl=12 * 3600,
    response_model=FreightosPageResponse,
)


# ═══════════════════════════════════════════════════════════════
# IMF PortWatch — daily chokepoint transit volumes (ArcGIS REST)
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Chokepoint:
    """PortWatch chokepoint catalog entry. `portname` is the exact value
    used in the ArcGIS WHERE clause; `region` groups for context."""

    portid: str
    portname: str
    label: str
    region: str


# 7 chokepoints with the highest trade-route signal. Skipped: the many
# secondary straits (Taiwan, Korea, Tsugaru, etc.) that are pre-positioning
# texture, not confirmation signal.
CHOKEPOINTS: dict[str, Chokepoint] = {
    "suez": Chokepoint("chokepoint1", "Suez Canal", "Suez Canal", "Red Sea"),
    "bab_el_mandeb": Chokepoint("chokepoint4", "Bab el-Mandeb Strait", "Bab el-Mandeb", "Red Sea"),
    "hormuz": Chokepoint("chokepoint6", "Strait of Hormuz", "Hormuz", "Persian Gulf"),
    "panama": Chokepoint("chokepoint2", "Panama Canal", "Panama Canal", "Americas"),
    "good_hope": Chokepoint(
        "chokepoint7", "Cape of Good Hope", "Cape of Good Hope", "Africa (reroute)"
    ),
    "bosporus": Chokepoint("chokepoint3", "Bosporus Strait", "Bosporus", "Black Sea"),
    "malacca": Chokepoint("chokepoint5", "Malacca Strait", "Malacca", "SE Asia"),
}


@dataclass
class ChokepointQueryRequest(ParamsRequest):
    """Fetch the latest N daily observations for one chokepoint by name.

    Default 365 supports trailing-year-mean baseline. ArcGIS server
    enforces resultRecordCount=1000 max; 365 is well under that.
    """

    portname: str
    record_count: int = 365

    def to_params(self) -> dict[str, str]:
        return {
            "where": f"portname = '{self.portname}'",
            "outFields": "date,portname,n_container,n_total,capacity",
            "orderByFields": "date DESC",
            "resultRecordCount": str(self.record_count),
            "f": "json",
        }


@dataclass
class ChokepointObservation:
    date: str
    n_container: int
    n_total: int
    capacity: int


@dataclass
class ChokepointDataResponse:
    """Daily transit observations for one chokepoint.

    Rows are date-ascending so [-1] is the latest day. The `date` field
    is an ISO string (the layer's `date` column is esriFieldTypeDateOnly,
    not a unix-millis timestamp — string-sort is correct).
    """

    portname: str | None = None
    observations: list[ChokepointObservation] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: Any) -> "ChokepointDataResponse":
        if not isinstance(data, dict):
            return cls()
        feats = data.get("features") or []
        portname: str | None = None
        rows: list[ChokepointObservation] = []
        for f in feats:
            attrs = f.get("attributes") or {}
            if portname is None and attrs.get("portname"):
                portname = attrs["portname"]
            d = attrs.get("date")
            if not d:
                continue
            rows.append(
                ChokepointObservation(
                    date=d,
                    n_container=int(attrs.get("n_container") or 0),
                    n_total=int(attrs.get("n_total") or 0),
                    capacity=int(attrs.get("capacity") or 0),
                )
            )
        rows.sort(key=lambda r: r.date)
        return cls(portname=portname, observations=rows)

    def to_output(self) -> str:
        if not self.observations:
            return f"(no observations for {self.portname or 'chokepoint'})"
        last = self.observations[-1]
        return (
            f"{self.portname}: latest {last.date} container={last.n_container} "
            f"total={last.n_total} (n={len(self.observations)})"
        )


PORTWATCH_CHOKEPOINTS_QUERY = Endpoint(
    "/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query",
    cache_ttl=6 * 3600,
    response_model=ChokepointDataResponse,
)
