"""FINRA Query API endpoints — market-wide corporate credit breadth and flow.

What the free credential buys, after accepting the Fixed Income Data agreement,
is the *aggregate* corporate bond tape: per session, how many bonds rose vs fell,
how many hit 52-week highs vs lows, and how volume split between customers
buying, customers selling, and dealers trading with each other. Split out by
grade (IG / HY / convertibles) and — separately — for the **144A** market alone.

The 144A cut is the reason this exists. 144A is the private-placement channel
that speculative issuers fund through, so its breadth is a direct daily read on
the health of that funding market, which a single broad HY OAS number cannot
isolate.

What it is *not*: there are no CUSIP-level prices here. The `trace*` datasets
that sound like they'd have them are (a) a paid Firm tier and (b) firm execution
-quality report cards, not bond quotes. Single-name marks come from SSGA.

**Field-name trap.** The two dataset families use `productCategory` and
`tradeType` to mean opposite things:

    corporateMarketBreadth   productCategory = grade   (investment grade / high yield / ...)
    corporateMarketSentiment productCategory = **side** (customer buy / inter-dealer / ...)
                             tradeType       = **grade**

Read them the way the *data* uses them, not the way the names read. Both response
models below normalize to `grade` / `side` so callers never see the swap.

**Query constraints.** `tradeReportDate` is a partition key, so every request
must pin it with an EQUAL compareFilter — one HTTP round trip per session, which
makes long backfills expensive and per-date caching essential. Weekends and
holidays return 204 with an empty body, which is a valid answer, not an error.
Requests must send `Accept: application/json`; the default response is CSV.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint
from trading_clients.table_helpers import md_table

GROUP = "fixedIncomeMarket"

# Grades as FINRA labels them, in the order we present.
GRADE_ALL = "all securities"
GRADE_IG = "investment grade"
GRADE_HY = "high yield"
GRADE_CONV = "convertibles"
GRADE_ORDER = (GRADE_ALL, GRADE_IG, GRADE_HY, GRADE_CONV)

# Trade sides in the sentiment datasets.
SIDE_ALL = "all securities"
SIDE_CUSTOMER_BUY = "customer buy"
SIDE_CUSTOMER_SELL = "customer sell"
SIDE_AFFILIATE_BUY = "affiliate buy"
SIDE_AFFILIATE_SELL = "affiliate sell"
SIDE_INTER_DEALER = "inter-dealer"


def _parse_date(raw: Any) -> date | None:
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_int(raw: Any) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _to_float(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class TradeDateRequest(BodyRequest):
    """One session of a partitioned dataset.

    `trade_date` is mandatory in practice: it is a partition key, and without an
    EQUAL compareFilter on it the API rejects sorting and scans unboundedly.
    """

    trade_date: date
    limit: int = 100

    def to_body(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "compareFilters": [
                {
                    "fieldName": "tradeReportDate",
                    "fieldValue": self.trade_date.isoformat(),
                    "compareType": "EQUAL",
                }
            ],
        }


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class BreadthRow:
    """Advance/decline and 52-week extremes for one grade on one session."""

    trade_date: date | None
    grade: str
    total_trades: int
    advances: int
    declines: int
    unchanged: int
    fifty_two_week_high: int
    fifty_two_week_low: int
    total_volume_mm: float

    @property
    def ad_ratio(self) -> float | None:
        """Advances per decline. None when nothing declined (no signal, not infinity)."""
        return self.advances / self.declines if self.declines else None

    @property
    def net_new_highs(self) -> int:
        """52-week highs minus lows. Negative = more bonds at 52w lows."""
        return self.fifty_two_week_high - self.fifty_two_week_low


@dataclass
class MarketBreadthResponse:
    rows: list[BreadthRow] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: Any) -> MarketBreadthResponse:
        rows = [
            BreadthRow(
                trade_date=_parse_date(r.get("tradeReportDate")),
                # In THIS dataset productCategory is the grade (see module docstring).
                grade=str(r.get("productCategory") or ""),
                total_trades=_to_int(r.get("totalTrades")),
                advances=_to_int(r.get("advances")),
                declines=_to_int(r.get("declines")),
                unchanged=_to_int(r.get("unchanged")),
                fifty_two_week_high=_to_int(r.get("fiftyTwoWeekHigh")),
                fifty_two_week_low=_to_int(r.get("fiftyTwoWeekLow")),
                total_volume_mm=_to_float(r.get("totalVolume")),
            )
            for r in (data or [])
            if isinstance(r, dict)
        ]
        return cls(rows=rows)

    def by_grade(self, grade: str) -> BreadthRow | None:
        for r in self.rows:
            if r.grade == grade:
                return r
        return None

    @property
    def trade_date(self) -> date | None:
        return self.rows[0].trade_date if self.rows else None

    def to_output(self) -> str:
        if not self.rows:
            return "(no breadth data)"
        ordered = [r for g in GRADE_ORDER for r in self.rows if r.grade == g]
        ordered += [r for r in self.rows if r.grade not in GRADE_ORDER]
        return md_table(
            ["Grade", "Trades", "Adv", "Dec", "A/D", "52w Hi", "52w Lo", "Net Hi", "Vol $MM"],
            [
                [
                    r.grade,
                    f"{r.total_trades:,}",
                    f"{r.advances:,}",
                    f"{r.declines:,}",
                    f"{r.ad_ratio:.2f}" if r.ad_ratio is not None else "—",
                    f"{r.fifty_two_week_high:,}",
                    f"{r.fifty_two_week_low:,}",
                    f"{r.net_new_highs:+,}",
                    f"{r.total_volume_mm:,.0f}",
                ]
                for r in ordered
            ],
        )


@dataclass
class SentimentRow:
    """Volume for one (grade, side) pair on one session."""

    trade_date: date | None
    grade: str
    side: str
    total_trades: int
    total_transactions: int
    total_volume_mm: float


@dataclass
class MarketSentimentResponse:
    rows: list[SentimentRow] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: Any) -> MarketSentimentResponse:
        rows = [
            SentimentRow(
                trade_date=_parse_date(r.get("tradeReportDate")),
                # Swapped relative to the breadth dataset — see module docstring.
                grade=str(r.get("tradeType") or ""),
                side=str(r.get("productCategory") or ""),
                total_trades=_to_int(r.get("totalTrades")),
                total_transactions=_to_int(r.get("totalTransactions")),
                total_volume_mm=_to_float(r.get("totalVolume")),
            )
            for r in (data or [])
            if isinstance(r, dict)
        ]
        return cls(rows=rows)

    def lookup(self, grade: str, side: str) -> SentimentRow | None:
        for r in self.rows:
            if r.grade == grade and r.side == side:
                return r
        return None

    def net_customer_mm(self, grade: str) -> float | None:
        """Customer buy volume minus customer sell volume, $MM.

        Positive = customers net lifting bonds from dealers (dealer inventory
        falling). This is the flow side of the read: breadth says where prices
        went, this says who had to take the other side.
        """
        buy = self.lookup(grade, SIDE_CUSTOMER_BUY)
        sell = self.lookup(grade, SIDE_CUSTOMER_SELL)
        if buy is None or sell is None:
            return None
        return buy.total_volume_mm - sell.total_volume_mm

    @property
    def trade_date(self) -> date | None:
        return self.rows[0].trade_date if self.rows else None

    def to_output(self) -> str:
        if not self.rows:
            return "(no sentiment data)"
        grades = [g for g in GRADE_ORDER if any(r.grade == g for r in self.rows)]
        sides = (SIDE_CUSTOMER_BUY, SIDE_CUSTOMER_SELL, SIDE_INTER_DEALER)
        out_rows = []
        for g in grades:
            cells = [g]
            for s in sides:
                row = self.lookup(g, s)
                cells.append(f"{row.total_volume_mm:,.0f}" if row else "—")
            net = self.net_customer_mm(g)
            cells.append(f"{net:+,.0f}" if net is not None else "—")
            out_rows.append(cells)
        return md_table(
            ["Grade", "Cust buy $MM", "Cust sell $MM", "Inter-dealer $MM", "Net cust $MM"],
            out_rows,
        )


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# A published session never changes, so these cache for a day; the client
# shortens the TTL for a date that may still be filling in.
_TTL = 86400


def _path(name: str) -> str:
    return f"/data/group/{GROUP}/name/{name}"


MARKET_BREADTH = Endpoint(
    _path("corporateMarketBreadth"),
    cache_ttl=_TTL,
    response_model=MarketBreadthResponse,
)

MARKET_BREADTH_144A = Endpoint(
    _path("corporate144AMarketBreadth"),
    cache_ttl=_TTL,
    response_model=MarketBreadthResponse,
)

MARKET_SENTIMENT = Endpoint(
    _path("corporateMarketSentiment"),
    cache_ttl=_TTL,
    response_model=MarketSentimentResponse,
)

MARKET_SENTIMENT_144A = Endpoint(
    _path("corporate144AMarketSentiment"),
    cache_ttl=_TTL,
    response_model=MarketSentimentResponse,
)
