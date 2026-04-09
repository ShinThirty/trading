"""FMP API endpoint definitions with typed request/response models."""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.table_helpers import fmt_large, fmt_number, kv_table, list_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class SymbolRequest(ParamsRequest):
    symbol: str

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol}


@dataclass
class FinancialRequest(ParamsRequest):
    symbol: str
    period: str = "annual"
    limit: int = 4

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "period": self.period, "limit": str(self.limit)}


@dataclass
class EarningsRequest(ParamsRequest):
    symbol: str
    limit: int = 5

    def to_params(self) -> dict[str, str]:
        return {"symbol": self.symbol, "limit": str(self.limit)}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class ProfileResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "ProfileResponse":
        return cls(data=data or {})

    def to_markdown(self) -> str:
        if not self.data:
            return "(no data)"
        return kv_table(
            {
                "Name": self.data.get("companyName"),
                "Symbol": self.data.get("symbol"),
                "Price": fmt_number(self.data.get("price")),
                "Market Cap": fmt_large(self.data.get("marketCap")),
                "Beta": fmt_number(self.data.get("beta")),
                "Vol Avg": fmt_large(self.data.get("averageVolume")),
                "Last Dividend": fmt_number(self.data.get("lastDividend")),
                "52W Range": self.data.get("range", ""),
                "Sector": self.data.get("sector"),
                "Industry": self.data.get("industry"),
                "Exchange": self.data.get("exchange"),
                "CEO": self.data.get("ceo"),
            }
        )


@dataclass
class IncomeStatementResponse:
    statements: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "IncomeStatementResponse":
        return cls(statements=data or [])

    def to_markdown(self) -> str:
        if not self.statements:
            return "(no data)"
        rows = [
            {
                "Date": s.get("date", ""),
                "Revenue": fmt_large(s.get("revenue")),
                "Gross Profit": fmt_large(s.get("grossProfit")),
                "Op Income": fmt_large(s.get("operatingIncome")),
                "Net Income": fmt_large(s.get("netIncome")),
                "EPS": fmt_number(s.get("eps")),
                "EBITDA": fmt_large(s.get("ebitda")),
            }
            for s in self.statements
        ]
        return list_table(rows)


@dataclass
class BalanceSheetResponse:
    statements: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "BalanceSheetResponse":
        return cls(statements=data or [])

    def to_markdown(self) -> str:
        if not self.statements:
            return "(no data)"
        rows = [
            {
                "Date": s.get("date", ""),
                "Total Assets": fmt_large(s.get("totalAssets")),
                "Total Liab": fmt_large(s.get("totalLiabilities")),
                "Total Equity": fmt_large(s.get("totalStockholdersEquity")),
                "Cash": fmt_large(s.get("cashAndCashEquivalents")),
                "Total Debt": fmt_large(s.get("totalDebt")),
            }
            for s in self.statements
        ]
        return list_table(rows)


@dataclass
class CashFlowResponse:
    statements: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "CashFlowResponse":
        return cls(statements=data or [])

    def to_markdown(self) -> str:
        if not self.statements:
            return "(no data)"
        rows = [
            {
                "Date": s.get("date", ""),
                "Operating CF": fmt_large(s.get("operatingCashFlow")),
                "Capex": fmt_large(s.get("capitalExpenditure")),
                "Free CF": fmt_large(s.get("freeCashFlow")),
                "Dividends": fmt_large(s.get("commonDividendsPaid")),
                "Buybacks": fmt_large(s.get("commonStockRepurchased")),
            }
            for s in self.statements
        ]
        return list_table(rows)


@dataclass
class KeyMetricsResponse:
    metrics: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "KeyMetricsResponse":
        return cls(metrics=data or [])

    def to_markdown(self) -> str:
        if not self.metrics:
            return "(no data)"
        rows = [
            {
                "Date": m.get("date", ""),
                "EV/EBITDA": fmt_number(m.get("evToEBITDA")),
                "EV/Sales": fmt_number(m.get("evToSales")),
                "ROE": fmt_number(m.get("returnOnEquity")),
                "ROA": fmt_number(m.get("returnOnAssets")),
                "Curr Ratio": fmt_number(m.get("currentRatio")),
                "Net Debt/EBITDA": fmt_number(m.get("netDebtToEBITDA")),
                "FCF Yield": fmt_number(m.get("freeCashFlowYield"), 4),
            }
            for m in self.metrics
        ]
        return list_table(rows)


@dataclass
class FmpEarningsResponse:
    earnings: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "FmpEarningsResponse":
        return cls(earnings=data or [])

    def to_markdown(self) -> str:
        if not self.earnings:
            return "(no data)"
        rows = [
            {
                "Date": e.get("date", ""),
                "Symbol": e.get("symbol", ""),
                "EPS Est": fmt_number(e.get("epsEstimated")),
                "EPS Act": fmt_number(e.get("epsActual")),
                "Rev Est": fmt_large(e.get("revenueEstimated")),
                "Rev Act": fmt_large(e.get("revenueActual")),
            }
            for e in self.earnings
        ]
        return list_table(rows)


@dataclass
class DividendHistoryResponse:
    dividends: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "DividendHistoryResponse":
        return cls(dividends=data or [])

    def to_markdown(self) -> str:
        if not self.dividends:
            return "(no dividends)"
        rows = [
            {
                "Ex-Date": d.get("date", ""),
                "Pay Date": d.get("paymentDate", ""),
                "Record Date": d.get("recordDate", ""),
                "Declaration": d.get("declarationDate", ""),
                "Dividend": fmt_number(d.get("dividend"), 4),
                "Adj Dividend": fmt_number(d.get("adjDividend"), 4),
            }
            for d in self.dividends
        ]
        return list_table(rows)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

PROFILE = Endpoint(
    "/profile",
    cache_ttl=3600,
    response_model=ProfileResponse,
    extract=lambda d: d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {}),
)

INCOME_STATEMENT = Endpoint(
    "/income-statement", cache_ttl=3600, response_model=IncomeStatementResponse
)

BALANCE_SHEET = Endpoint(
    "/balance-sheet-statement", cache_ttl=3600, response_model=BalanceSheetResponse
)

CASH_FLOW = Endpoint("/cash-flow-statement", cache_ttl=3600, response_model=CashFlowResponse)

KEY_METRICS = Endpoint("/key-metrics", cache_ttl=3600, response_model=KeyMetricsResponse)

EARNINGS = Endpoint("/earnings", cache_ttl=3600, response_model=FmpEarningsResponse)

DIVIDEND_HISTORY = Endpoint("/dividends", cache_ttl=3600, response_model=DividendHistoryResponse)
