"""CFTC Commitments of Traders (COT) endpoint definitions.

Source: CFTC Public Reporting (Socrata). No auth required.

Three weekly reports are exposed:
  - TFF (Traders in Financial Futures): financial contracts. Categories
    include Asset Manager and Leveraged Money — combined as the "spec" proxy.
  - Disaggregated: physical commodity contracts. Managed Money is the spec proxy.
  - Legacy: catch-all schema. Non-commercial is the spec proxy.

Each contract is fetched against the appropriate report by `market_and_exchange_names`
prefix LIKE. The response model auto-detects report format by which long/short field
names are populated, so callers don't need to thread the report type through.

Net spec positioning (= long - short) is the headline number; we compute the
52-week z-score and percentile so extremes are easy to surface.
"""

from dataclasses import dataclass, field
from statistics import mean, pstdev

from trading_clients.endpoint import Endpoint, ParamsRequest

# ═══════════════════════════════════════════════════════════════
# Curated contract catalogue
# ═══════════════════════════════════════════════════════════════
#
# Maps friendly keys (used by MCP tool callers) to:
#   - report endpoint key: "tff" | "disagg" | "legacy"
#   - market_and_exchange_names prefix (LIKE pattern; we append %)
#   - human-readable label
#
# Names are CFTC's canonical strings — verified against current weekly reports
# (2026-05). If CFTC renames a contract, edit here. Patterns are LIKE prefixes.
CONTRACTS: dict[str, tuple[str, str, str]] = {
    "SPX": ("tff", "E-MINI S&P 500", "E-mini S&P 500"),
    "NDX": ("tff", "NASDAQ-100 Consolidated", "Nasdaq-100 (consolidated)"),
    "VIX": ("tff", "VIX FUTURES", "VIX futures"),
    "10Y": ("tff", "UST 10Y NOTE", "10Y Treasury Note"),
    "GOLD": ("disagg", "GOLD - COMMODITY", "Gold (COMEX)"),
    "WTI": ("disagg", "WTI-PHYSICAL", "WTI Crude Oil (NYMEX)"),
}


# ═══════════════════════════════════════════════════════════════
# Request Model
# ═══════════════════════════════════════════════════════════════


@dataclass
class GetCotRequest(ParamsRequest):
    """Fetch the most recent N weeks of COT reports for a contract.

    market_pattern: prefix for `market_and_exchange_names` (we append %).
    weeks: number of historical reports (default 53 — gives 1y of weekly z-score).
    """

    market_pattern: str
    weeks: int = 53

    def to_params(self) -> dict[str, str]:
        # SoQL LIKE on market_and_exchange_names; quote escaping not needed for
        # the curated patterns (no apostrophes), but we keep the where simple.
        where = f"market_and_exchange_names like '{self.market_pattern}%'"
        return {
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(self.weeks),
        }


# ═══════════════════════════════════════════════════════════════
# Response Model
# ═══════════════════════════════════════════════════════════════


def _f(rec: dict, key: str) -> float | None:
    """Cast a Socrata field (string) to float, return None if missing/invalid."""
    raw = rec.get(key)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _spec_net(rec: dict) -> float | None:
    """Compute net spec positioning, auto-detecting the report format.

    Detection precedence: TFF (asset_mgr + lev_money) → Disaggregated (m_money) →
    Legacy (noncomm). We pick the first whose long-side field is present.
    """
    # TFF — sum Asset Manager + Leveraged Money
    if rec.get("asset_mgr_positions_long") is not None:
        am_l = _f(rec, "asset_mgr_positions_long") or 0.0
        am_s = _f(rec, "asset_mgr_positions_short") or 0.0
        lm_l = _f(rec, "lev_money_positions_long") or 0.0
        lm_s = _f(rec, "lev_money_positions_short") or 0.0
        return (am_l + lm_l) - (am_s + lm_s)
    # Disaggregated — Managed Money
    if rec.get("m_money_positions_long_all") is not None:
        long = _f(rec, "m_money_positions_long_all") or 0.0
        short = _f(rec, "m_money_positions_short_all") or 0.0
        return long - short
    # Legacy — Non-commercial
    if rec.get("noncomm_positions_long_all") is not None:
        long = _f(rec, "noncomm_positions_long_all") or 0.0
        short = _f(rec, "noncomm_positions_short_all") or 0.0
        return long - short
    return None


@dataclass
class CotReportResponse:
    """A contract's recent weekly COT reports, newest first.

    `weekly` is the raw record list; `nets` is the parsed net-spec time series
    (newest-first), with z-score and percentile computed against the trailing
    window. `latest_date` is the report date of the most recent observation.
    """

    weekly: list[dict] = field(default_factory=list)
    nets: list[float] = field(default_factory=list)
    latest_date: str = ""
    open_interest: float | None = None

    @classmethod
    def from_response(cls, data: list[dict]) -> "CotReportResponse":
        records = data or []
        nets: list[float] = []
        for rec in records:
            n = _spec_net(rec)
            if n is not None:
                nets.append(n)
        latest_date = records[0].get("report_date_as_yyyy_mm_dd", "")[:10] if records else ""
        oi = _f(records[0], "open_interest_all") if records else None
        return cls(weekly=records, nets=nets, latest_date=latest_date, open_interest=oi)

    @property
    def latest_net(self) -> float | None:
        return self.nets[0] if self.nets else None

    @property
    def prior_net(self) -> float | None:
        return self.nets[1] if len(self.nets) > 1 else None

    @property
    def wow_change(self) -> float | None:
        if self.latest_net is None or self.prior_net is None:
            return None
        return self.latest_net - self.prior_net

    @property
    def z_score(self) -> float | None:
        """52-week (or available) z-score on net spec positioning."""
        if len(self.nets) < 8:
            return None
        sample = self.nets[: min(len(self.nets), 53)]
        mu = mean(sample)
        sd = pstdev(sample)
        if sd == 0:
            return None
        return (sample[0] - mu) / sd

    @property
    def percentile(self) -> float | None:
        """Where the latest net sits in the trailing window (0=lowest, 100=highest)."""
        if len(self.nets) < 8:
            return None
        sample = self.nets[: min(len(self.nets), 53)]
        latest = sample[0]
        below = sum(1 for v in sample[1:] if v < latest)
        return below / (len(sample) - 1) * 100

    def to_output(self) -> str:
        if not self.weekly:
            return "(no COT data)"
        lines = [f"Latest report: {self.latest_date}"]
        if self.latest_net is not None:
            lines.append(f"Net spec positioning: {self.latest_net:+,.0f} contracts")
        if self.wow_change is not None:
            lines.append(f"Week-over-week Δ: {self.wow_change:+,.0f}")
        if self.z_score is not None:
            lines.append(f"52w z-score: {self.z_score:+.2f}")
        if self.percentile is not None:
            lines.append(f"52w percentile: {self.percentile:.0f}%")
        if self.open_interest is not None:
            lines.append(f"Open interest: {self.open_interest:,.0f}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════
#
# Socrata dataset IDs (stable):
#   TFF Futures-Only:           gpe5-46if
#   Disaggregated Futures-Only: 72hh-3qpy
#   Legacy Futures-Only:        6dca-aqww
#
# Cache: 6h. Reports are released Friday 3:30pm ET; a long TTL is fine.

REPORT_TFF = Endpoint(
    "/resource/gpe5-46if.json",
    cache_ttl=21600,
    response_model=CotReportResponse,
)

REPORT_DISAGG = Endpoint(
    "/resource/72hh-3qpy.json",
    cache_ttl=21600,
    response_model=CotReportResponse,
)

REPORT_LEGACY = Endpoint(
    "/resource/6dca-aqww.json",
    cache_ttl=21600,
    response_model=CotReportResponse,
)

REPORTS: dict[str, Endpoint] = {
    "tff": REPORT_TFF,
    "disagg": REPORT_DISAGG,
    "legacy": REPORT_LEGACY,
}
