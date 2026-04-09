"""Finnhub API endpoint definitions with typed request/response models."""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.table_helpers import (
    fmt_large,
    fmt_number,
    kv_table,
    list_table,
    md_table,
    unix_to_date,
)

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class SymbolRequest(ParamsRequest):
    symbol: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol}


@dataclass
class CompanyNewsRequest(ParamsRequest):
    symbol: str
    from_date: str
    to_date: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "from": self.from_date, "to": self.to_date}


@dataclass
class MarketNewsRequest(ParamsRequest):
    category: str = "general"

    def to_params(self) -> dict[str, str]:
        return {"category": self.category}


@dataclass
class DateRangeRequest(ParamsRequest):
    from_date: str
    to_date: str

    def to_params(self) -> dict[str, str]:
        return {"from": self.from_date, "to": self.to_date}


@dataclass
class BasicFinancialsRequest(ParamsRequest):
    symbol: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "metric": "all"}


@dataclass
class DividendsRequest(ParamsRequest):
    symbol: str
    from_date: str
    to_date: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "from": self.from_date, "to": self.to_date}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class NewsResponse:
    articles: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "NewsResponse":
        return cls(articles=data or [])

    def to_markdown(self) -> str:
        if not self.articles:
            return "(no news)"
        rows = [
            {
                "Date": unix_to_date(a.get("datetime")),
                "Headline": a.get("headline", ""),
                "Source": a.get("source", ""),
            }
            for a in self.articles
        ]
        return list_table(rows)


@dataclass
class EconomicCalendarResponse:
    events: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "EconomicCalendarResponse":
        return cls(events=data or [])

    def to_markdown(self) -> str:
        if not self.events:
            return "(no events)"
        rows = [
            {
                "Date": e.get("time", ""),
                "Event": e.get("event", ""),
                "Country": e.get("country", ""),
                "Actual": str(e.get("actual", "")),
                "Estimate": str(e.get("estimate", "")),
                "Previous": str(e.get("prev", "")),
                "Impact": e.get("impact", ""),
            }
            for e in self.events
        ]
        return list_table(rows)


@dataclass
class EarningsCalendarResponse:
    earnings: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "EarningsCalendarResponse":
        return cls(earnings=data or [])

    def to_markdown(self) -> str:
        if not self.earnings:
            return "(no earnings)"
        rows = [
            {
                "Date": e.get("date", ""),
                "Symbol": e.get("symbol", ""),
                "Hour": e.get("hour", ""),
                "EPS Est": fmt_number(e.get("epsEstimate")),
                "EPS Act": fmt_number(e.get("epsActual")),
                "Rev Est": fmt_large(e.get("revenueEstimate")),
                "Rev Act": fmt_large(e.get("revenueActual")),
            }
            for e in self.earnings
        ]
        return list_table(rows)


@dataclass
class BasicFinancialsResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "BasicFinancialsResponse":
        return cls(data=data or {})

    def to_markdown(self) -> str:
        metric = self.data.get("metric", {})
        if not metric:
            return "(no metrics)"
        mc = metric.get("marketCapitalization")
        selected = {
            "P/E (TTM)": fmt_number(metric.get("peNormalizedAnnual")),
            "P/B": fmt_number(metric.get("pbAnnual")),
            "EPS (TTM)": fmt_number(metric.get("epsNormalizedAnnual")),
            "Dividend Yield %": fmt_number(metric.get("dividendYieldIndicatedAnnual")),
            "Beta": fmt_number(metric.get("beta")),
            "52W High": fmt_number(metric.get("52WeekHigh")),
            "52W Low": fmt_number(metric.get("52WeekLow")),
            "Market Cap": fmt_large(mc * 1e6) if mc else "",
            "ROE (TTM)": fmt_number(metric.get("roeTTM")),
            "Debt/Equity": fmt_number(metric.get("totalDebt/totalEquityAnnual")),
            "Current Ratio": fmt_number(metric.get("currentRatioAnnual")),
            "Revenue/Share (TTM)": fmt_number(metric.get("revenuePerShareTTM")),
        }
        return kv_table({k: v for k, v in selected.items() if v})


@dataclass
class EpsEstimatesResponse:
    estimates: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "EpsEstimatesResponse":
        return cls(estimates=data or [])

    def to_markdown(self) -> str:
        if not self.estimates:
            return "(no estimates)"
        rows = [
            {
                "Period": e.get("period", ""),
                "Avg": fmt_number(e.get("epsAvg")),
                "High": fmt_number(e.get("epsHigh")),
                "Low": fmt_number(e.get("epsLow")),
                "# Analysts": str(e.get("numberAnalysts", "")),
            }
            for e in self.estimates
        ]
        return list_table(rows)


@dataclass
class RecommendationsResponse:
    trends: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "RecommendationsResponse":
        return cls(trends=data or [])

    def to_markdown(self) -> str:
        if not self.trends:
            return "(no data)"
        rows = [
            {
                "Period": r.get("period", ""),
                "Strong Buy": str(r.get("strongBuy", "")),
                "Buy": str(r.get("buy", "")),
                "Hold": str(r.get("hold", "")),
                "Sell": str(r.get("sell", "")),
                "Strong Sell": str(r.get("strongSell", "")),
            }
            for r in self.trends
        ]
        return list_table(rows)


@dataclass
class PriceTargetResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "PriceTargetResponse":
        return cls(data=data or {})

    def to_markdown(self) -> str:
        if not self.data:
            return "(no data)"
        return kv_table(
            {
                "Symbol": self.data.get("symbol"),
                "Target High": fmt_number(self.data.get("targetHigh")),
                "Target Low": fmt_number(self.data.get("targetLow")),
                "Target Mean": fmt_number(self.data.get("targetMean")),
                "Target Median": fmt_number(self.data.get("targetMedian")),
                "Last Updated": self.data.get("lastUpdated", ""),
            }
        )


@dataclass
class InsiderTransactionsResponse:
    transactions: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "InsiderTransactionsResponse":
        return cls(transactions=data or [])

    def to_markdown(self) -> str:
        if not self.transactions:
            return "(no transactions)"
        rows = [
            {
                "Date": t.get("transactionDate", ""),
                "Name": t.get("name", ""),
                "Share": fmt_number(t.get("share"), 0),
                "Change": fmt_number(t.get("change"), 0),
                "Price": fmt_number(t.get("transactionPrice")),
                "Type": t.get("transactionCode", ""),
            }
            for t in self.transactions
        ]
        return list_table(rows)


@dataclass
class PeersResponse:
    peers: list[str]

    @classmethod
    def from_response(cls, data: list[str]) -> "PeersResponse":
        return cls(peers=data or [])

    def to_markdown(self) -> str:
        if not self.peers:
            return "(no peers)"
        return md_table(["Symbol"], [[s] for s in self.peers])


@dataclass
class DividendsResponse:
    dividends: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "DividendsResponse":
        return cls(dividends=data or [])

    def to_markdown(self) -> str:
        if not self.dividends:
            return "(no dividends)"
        rows = [
            {
                "Ex-Date": d.get("date", ""),
                "Pay Date": d.get("payDate", ""),
                "Record Date": d.get("recordDate", ""),
                "Amount": fmt_number(d.get("amount"), 4),
                "Currency": d.get("currency", ""),
            }
            for d in self.dividends
        ]
        return list_table(rows)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

COMPANY_NEWS = Endpoint("/company-news", cache_ttl=300, response_model=NewsResponse)

MARKET_NEWS = Endpoint("/news", cache_ttl=300, response_model=NewsResponse)

ECONOMIC_CALENDAR = Endpoint(
    "/calendar/economic",
    cache_ttl=3600,
    response_model=EconomicCalendarResponse,
    extract=lambda d: d.get("economicCalendar", []),
)

EARNINGS_CALENDAR = Endpoint(
    "/calendar/earnings",
    cache_ttl=3600,
    response_model=EarningsCalendarResponse,
    extract=lambda d: [
        e
        for e in d.get("earningsCalendar", [])
        if e.get("epsEstimate") is not None or e.get("revenueEstimate")
    ],
)

BASIC_FINANCIALS = Endpoint("/stock/metric", cache_ttl=3600, response_model=BasicFinancialsResponse)

EPS_ESTIMATES = Endpoint("/stock/eps-estimate", cache_ttl=3600, response_model=EpsEstimatesResponse)

RECOMMENDATIONS = Endpoint(
    "/stock/recommendation", cache_ttl=3600, response_model=RecommendationsResponse
)

PRICE_TARGET = Endpoint("/stock/price-target", cache_ttl=3600, response_model=PriceTargetResponse)

INSIDER_TRANSACTIONS = Endpoint(
    "/stock/insider-transactions",
    cache_ttl=3600,
    response_model=InsiderTransactionsResponse,
    extract=lambda d: d.get("data", []),
)

PEERS = Endpoint("/stock/peers", cache_ttl=3600, response_model=PeersResponse)

DIVIDENDS = Endpoint("/stock/dividend", cache_ttl=3600, response_model=DividendsResponse)
