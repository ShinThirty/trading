"""TastyTrade API endpoint definitions with typed request/response models."""

from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint, ParamsRequest, PathRequest
from trading_clients.table_helpers import fmt_number, list_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class MarketMetricsRequest(ParamsRequest):
    symbols: str  # comma-separated, e.g. "AAPL,QCOM"

    def to_params(self) -> dict[str, str]:
        return {"symbols": self.symbols}


@dataclass
class DividendHistoryRequest(PathRequest, ParamsRequest):
    symbol: str

    def to_path_params(self) -> dict[str, str]:
        return {"symbol": self.symbol}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class WatchlistRequest(PathRequest, ParamsRequest):
    name: str

    def to_path_params(self) -> dict[str, str]:
        return {"name": self.name}

    def to_params(self) -> dict[str, str]:
        return {}


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

    def to_output(self) -> str:
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


@dataclass
class DividendHistoryResponse:
    dividends: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "DividendHistoryResponse":
        return cls(dividends=data or [])

    def to_output(self) -> str:
        if not self.dividends:
            return "(no dividends)"
        entries = [
            f"{d.get('occurred-date', '')} ${fmt_number(d.get('amount'), 4)}"
            for d in self.dividends
        ]
        return ", ".join(entries)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

MARKET_METRICS = Endpoint(
    "/market-metrics",
    cache_ttl=300,
    response_model=MarketMetricsResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)

DIVIDEND_HISTORY = Endpoint(
    "/market-metrics/historic-corporate-events/dividends/{symbol}",
    cache_ttl=3600,
    response_model=DividendHistoryResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)


@dataclass
class WatchlistsResponse:
    watchlists: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "WatchlistsResponse":
        return cls(watchlists=data or [])

    def to_output(self) -> str:
        if not self.watchlists:
            return "(no watchlists)"
        entries = [
            f"{w.get('name', '')} ({len(w.get('watchlist-entries', []))})" for w in self.watchlists
        ]
        return ", ".join(entries)


@dataclass
class WatchlistDetailResponse:
    watchlist: dict

    @classmethod
    def from_response(cls, data: dict) -> "WatchlistDetailResponse":
        return cls(watchlist=data or {})

    def to_output(self) -> str:
        if not self.watchlist:
            return "(no watchlist)"
        entries = self.watchlist.get("watchlist-entries", [])
        if not entries:
            return "(empty watchlist)"
        name = self.watchlist.get("name", "Watchlist")
        symbols = [e.get("symbol", "") for e in entries if e.get("symbol")]
        return f"**{name}** ({len(symbols)} symbols): {', '.join(symbols)}"


PUBLIC_WATCHLISTS = Endpoint(
    "/public-watchlists",
    cache_ttl=3600,
    response_model=WatchlistsResponse,
    extract=lambda d: d.get("data", {}).get("items", d.get("items", [])),
)

PUBLIC_WATCHLIST = Endpoint(
    "/public-watchlists/{name}",
    cache_ttl=3600,
    response_model=WatchlistDetailResponse,
    extract=lambda d: d.get("data", d),
)


# ═══════════════════════════════════════════════════════════════
# Backtesting
# ═══════════════════════════════════════════════════════════════

BACKTESTER_URL = "https://backtester.vast.tastyworks.com"


@dataclass
class BacktestRequest(BodyRequest):
    symbol: str
    start_date: str
    end_date: str
    legs: list[dict]
    entry_conditions: dict
    exit_conditions: dict

    def to_body(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "legs": self.legs,
            "entryConditions": self.entry_conditions,
            "exitConditions": self.exit_conditions,
        }


@dataclass
class BacktestIdRequest(PathRequest, ParamsRequest):
    backtest_id: str

    def to_path_params(self) -> dict[str, str]:
        return {"id": self.backtest_id}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class BacktestResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "BacktestResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        if not self.data:
            return "(no data)"
        status = self.data.get("status", "")
        if status != "completed":
            progress = self.data.get("progress", 0)
            bt_id = self.data.get("id", "")
            return f"Backtest {bt_id}: {status} (progress: {progress})"

        results = self.data.get("results", self.data)
        trials = results.get("trials", [])
        stats = results.get("statistics", {})

        if not trials and not stats:
            return "(no trials — entry conditions may be too restrictive)"

        # Summary from statistics
        lines: list[str] = []
        if stats:
            lines.append(
                f"**{stats.get('Number of trades', 0)} trades** | "
                f"Win: {stats.get('Win percentage', '?')}% | "
                f"P&L: ${stats.get('Total profit/loss', '?')} | "
                f"Avg premium: ${stats.get('Avg. premium', '?')}"
            )
            lines.append(
                f"Avg win: ${stats.get('Avg. win size', '?')} | "
                f"Avg loss: ${stats.get('Avg. loss size', '?')} | "
                f"Worst: ${stats.get('Worst loss', '?')} | "
                f"Best: ${stats.get('Highest profit', '?')}"
            )
            lines.append(
                f"Avg DIT: {stats.get('Avg. days in trade', '?')} | "
                f"Max DD: {stats.get('Max drawdown', '?')}% on "
                f"{str(stats.get('Max drawdown date', ''))[:10]} | "
                f"BPR/trade: ${stats.get('Avg. BPR per trade', '?')}"
            )

        # Individual trials
        if trials:
            lines.append("")
            for t in trials:
                pnl = float(t.get("profitLoss", 0))
                m = "W" if pnl > 0 else "L"
                o = str(t.get("openDateTime", ""))[:10]
                c = str(t.get("closeDateTime", ""))[:10]
                lines.append(f"{m} {o} -> {c}: ${pnl:.2f}")

        return "\n".join(lines)


BACKTEST_CREATE = Endpoint(
    "/backtests",
    response_model=BacktestResponse,
    base_url=BACKTESTER_URL,
)

BACKTEST_GET = Endpoint(
    "/backtests/{id}",
    response_model=BacktestResponse,
    base_url=BACKTESTER_URL,
)
