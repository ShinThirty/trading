"""Finnhub API endpoint definitions with typed request/response models."""

from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.table_helpers import (
    fmt_large,
    fmt_number,
    kv_table,
    list_table,
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


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class NewsResponse:
    articles: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "NewsResponse":
        return cls(articles=data or [])

    def to_output(self) -> str:
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
class EarningsCalendarResponse:
    earnings: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "EarningsCalendarResponse":
        return cls(earnings=data or [])

    def to_output(self) -> str:
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

    def to_output(self) -> str:
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
class RecommendationsResponse:
    trends: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "RecommendationsResponse":
        return cls(trends=data or [])

    def to_output(self) -> str:
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
class InsiderTransactionsResponse:
    transactions: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "InsiderTransactionsResponse":
        return cls(transactions=data or [])

    def to_output(self) -> str:
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

    def to_output(self) -> str:
        if not self.peers:
            return "(no peers)"
        return ", ".join(self.peers)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

COMPANY_NEWS = Endpoint("/company-news", cache_ttl=300, response_model=NewsResponse)

MARKET_NEWS = Endpoint("/news", cache_ttl=300, response_model=NewsResponse)

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

RECOMMENDATIONS = Endpoint(
    "/stock/recommendation", cache_ttl=3600, response_model=RecommendationsResponse
)

INSIDER_TRANSACTIONS = Endpoint(
    "/stock/insider-transactions",
    cache_ttl=3600,
    response_model=InsiderTransactionsResponse,
    extract=lambda d: d.get("data", []),
)

PEERS = Endpoint("/stock/peers", cache_ttl=3600, response_model=PeersResponse)


# ═══════════════════════════════════════════════════════════════
# Financials Reported (SEC filings via Finnhub)
# ═══════════════════════════════════════════════════════════════

# XBRL concept suffixes to extract for each financial statement section.
# Each tuple: (display_name, [concept_suffix_variants]).
# First match wins; order matters for fallback.

_IC_ITEMS: list[tuple[str, list[str]]] = [
    (
        "Revenue",
        [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ],
    ),
    ("Cost of Revenue", ["CostOfGoodsAndServicesSold", "CostOfRevenue"]),
    ("Gross Profit", ["GrossProfit"]),
    ("Operating Income", ["OperatingIncomeLoss"]),
    ("Net Income", ["NetIncomeLoss", "ProfitLoss"]),
    ("EPS", ["EarningsPerShareDiluted"]),
]

_BS_ITEMS: list[tuple[str, list[str]]] = [
    (
        "Cash",
        [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsAndShortTermInvestments",
        ],
    ),
    ("Current Assets", ["AssetsCurrent"]),
    ("Total Assets", ["Assets"]),
    ("Current Liabilities", ["LiabilitiesCurrent"]),
    ("Long-term Debt", ["LongTermDebtNoncurrent", "LongTermDebt"]),
    ("Total Liabilities", ["Liabilities"]),
    (
        "Total Equity",
        [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
    ),
]

_CF_ITEMS: list[tuple[str, list[str]]] = [
    (
        # Continuing operations first: when a filer has discontinued operations the
        # plain concept folds them in, which inflates cash flow around a divestiture
        # and breaks the tie-out to the issuer's own reported free cash flow. Filers
        # without discontinued ops tag only the plain concept, where the two are equal.
        "Operating CF",
        [
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByOperatingActivities",
        ],
    ),
    (
        "Capex",
        [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ],
    ),
    (
        "Investing CF",
        [
            "NetCashProvidedByUsedInInvestingActivities",
            "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
        ],
    ),
    ("Dividends", ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]),
    ("Buybacks", ["PaymentsForRepurchaseOfCommonStock"]),
    (
        "Stock Comp",
        [
            "ShareBasedCompensation",
            "AllocatedShareBasedCompensationExpense",
        ],
    ),
    (
        "Financing CF",
        [
            "NetCashProvidedByUsedInFinancingActivities",
            "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
        ],
    ),
]


@dataclass
class FinancialsReportedRequest(ParamsRequest):
    symbol: str
    freq: str = "annual"

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "freq": self.freq}


@dataclass
class FinancialsReportedResponse:
    reports: list[dict]

    @classmethod
    def from_response(cls, data: dict) -> "FinancialsReportedResponse":
        return cls(reports=data.get("data", []) if isinstance(data, dict) else [])

    def _build_concept_map(self, report_section: list[dict]) -> dict[str, dict]:
        """Map concept suffix -> item dict for fast lookup."""
        result: dict[str, dict] = {}
        for item in report_section:
            concept = item.get("concept", "")
            # Strip prefix (e.g. 'us-gaap_' or 'panw_')
            suffix = concept.split("_", 1)[-1] if "_" in concept else concept
            if suffix not in result:
                result[suffix] = item
        return result

    def _extract_section(self, section: str, items: list[tuple[str, list[str]]], limit: int) -> str:
        if not self.reports:
            return "(no data)"
        rows = []
        for r in self.reports[:limit]:
            report = r.get("report", {})
            concepts = self._build_concept_map(report.get(section, []))
            row: dict[str, str] = {"Period": r.get("endDate", "")[:10]}
            form = r.get("form", "")
            if form:
                row["Filing"] = form
            for display_name, concept_names in items:
                for cn in concept_names:
                    if cn in concepts:
                        val = concepts[cn].get("value")
                        unit = concepts[cn].get("unit", "")
                        if unit == "usd" and isinstance(val, int | float):
                            row[display_name] = fmt_large(val)
                        elif isinstance(val, int | float):
                            row[display_name] = fmt_number(val)
                        else:
                            row[display_name] = str(val) if val is not None else ""
                        break
                else:
                    row[display_name] = ""
            rows.append(row)
        return list_table(rows)

    def _extract_numeric(
        self, section: str, items: list[tuple[str, list[str]]], limit: int
    ) -> list[dict[str, Any]]:
        """Extract raw numeric values (not formatted strings) for computation."""
        if not self.reports:
            return []
        rows: list[dict[str, Any]] = []
        for r in self.reports[:limit]:
            report = r.get("report", {})
            concepts = self._build_concept_map(report.get(section, []))
            row: dict[str, Any] = {
                "period": r.get("endDate", "")[:10],
                "form": r.get("form", ""),
                "fiscal_year": r.get("year"),
                "fiscal_quarter": r.get("quarter"),
            }
            for display_name, concept_names in items:
                for cn in concept_names:
                    if cn in concepts:
                        val = concepts[cn].get("value")
                        row[display_name] = val if isinstance(val, int | float) else None
                        break
                else:
                    row[display_name] = None
            rows.append(row)
        return rows

    def income_numeric(self, limit: int = 8) -> list[dict[str, Any]]:
        """Return raw income statement numbers for computation (revenue, operating income, etc)."""
        return self._extract_numeric("ic", _IC_ITEMS, limit)

    def cf_numeric(self, limit: int = 4) -> list[dict[str, Any]]:
        """Return raw cash flow numbers for computation (operating CF, capex, etc)."""
        return self._extract_numeric("cf", _CF_ITEMS, limit)

    def income_markdown(self, limit: int = 4) -> str:
        return self._extract_section("ic", _IC_ITEMS, limit)

    def balance_sheet_markdown(self, limit: int = 4) -> str:
        return self._extract_section("bs", _BS_ITEMS, limit)

    def cash_flow_markdown(self, limit: int = 4) -> str:
        return self._extract_section("cf", _CF_ITEMS, limit)

    def to_output(self) -> str:
        return self.income_markdown()


FINANCIALS_REPORTED = Endpoint(
    "/stock/financials-reported", cache_ttl=3600, response_model=FinancialsReportedResponse
)
