"""TastyTrade API endpoint definitions with typed request/response models."""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.table_helpers import list_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class MarketMetricsRequest(ParamsRequest):
    symbols: str  # comma-separated, e.g. "AAPL,QCOM"

    def to_params(self) -> dict[str, str]:
        return {"symbols": self.symbols}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


def _fmt_ratio_pct(val: float | str | None) -> str:
    """Format a decimal ratio (0.45) as a percentage string (45.0%)."""
    if val is None or val == "":
        return ""
    try:
        return f"{float(val) * 100:.1f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_raw_pct(val: float | str | None) -> str:
    """Format a value already in percentage units (27.85 → 27.9%)."""
    if val is None or val == "":
        return ""
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_earnings(earnings: dict | None) -> str:
    """Format earnings info: date + time-of-day + estimated flag."""
    if not earnings:
        return ""
    date = earnings.get("expected-report-date", "")
    if not date or date == "1970-01-01":
        return ""
    tod = earnings.get("time-of-day", "")
    estimated = earnings.get("estimated", False)
    parts = [date]
    if tod:
        parts.append(tod)
    if estimated:
        parts.append("(est)")
    return " ".join(parts)


@dataclass
class MarketMetricsResponse:
    items: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "MarketMetricsResponse":
        return cls(items=data or [])

    def to_markdown(self) -> str:
        if not self.items:
            return "(no metrics)"
        rows = []
        for item in self.items:
            row = {
                "Symbol": item.get("symbol", ""),
                "IV Index": _fmt_ratio_pct(item.get("implied-volatility-index")),
                "IV Rank": _fmt_ratio_pct(item.get("tw-implied-volatility-index-rank")),
                "IV Pctl": _fmt_ratio_pct(item.get("implied-volatility-percentile")),
                "IV 30d": _fmt_raw_pct(item.get("implied-volatility-30-day")),
                "HV 30d": _fmt_raw_pct(item.get("historical-volatility-30-day")),
                "IV-HV": _fmt_raw_pct(item.get("iv-hv-30-day-difference")),
                "Earnings": _fmt_earnings(item.get("earnings")),
                "Liq": str(item.get("liquidity-rating", "")),
            }
            rows.append(row)
        return list_table(rows)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

MARKET_METRICS = Endpoint(
    "/market-metrics",
    cache_ttl=300,
    response_model=MarketMetricsResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)
