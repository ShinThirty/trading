"""TWSE OpenAPI endpoint definitions.

TWSE (Taiwan Stock Exchange) publishes corporate disclosures as JSON via
https://openapi.twse.com.tw. The `t187ap05_L` feed carries the latest
monthly revenue for all ~1,000 listed companies in a single response,
released on the 10th of each month and refreshed as companies report.

For TSMC (2330) — the foundry layer underneath every advanced AI
accelerator — each row carries the current reporting month's revenue
plus prior-month and same-month-prior-year anchors, so a single call
gives us three explicit data points (and sometimes a fourth via YTD
arithmetic when the current month is Feb or Mar).

This feed replaced our prior scrape of investor.tsmc.com, which now
sits behind a Cloudflare browser challenge.
"""

from dataclasses import dataclass, field
from datetime import date

from trading_clients.endpoint import Endpoint, ParamsRequest

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class ListedMonthlyRevenueRequest(ParamsRequest):
    """The full listed-company feed is returned in one call — no params."""

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class MonthlyRevenueRow:
    """One company's most-recent monthly revenue print.

    revenue_*_thousands fields are NT$ thousands (as the feed reports —
    we keep the unit native so downstream callers can format to millions
    or billions consistently). mom_pct and yoy_pct are percentages
    computed by TWSE; we don't recompute them here.
    """

    company_code: str
    company_name: str
    industry: str
    year: int  # AD year (e.g. 2026)
    month: int  # 1-12
    revenue_curr_thousands: int
    revenue_prior_thousands: int | None
    revenue_lastyear_thousands: int | None
    ytd_revenue_thousands: int | None
    ytd_lastyear_thousands: int | None
    mom_pct: float | None
    yoy_pct: float | None
    ytd_yoy_pct: float | None
    publish_date: date | None


def _from_roc_yyyymmdd(s: str | None) -> date | None:
    """ROC 'YYYMMDD' (e.g. '1150417') → AD date 2026-04-17."""
    if not s or len(s) < 7:
        return None
    try:
        roc_year = int(s[:-4])
        month = int(s[-4:-2])
        day = int(s[-2:])
        return date(roc_year + 1911, month, day)
    except (ValueError, TypeError):
        return None


def _from_roc_yyyymm(s: str | None) -> tuple[int, int] | None:
    """ROC 'YYYMM' (e.g. '11503') → (2026, 3)."""
    if not s or len(s) < 4:
        return None
    try:
        roc_year = int(s[:-2])
        month = int(s[-2:])
        return roc_year + 1911, month
    except (ValueError, TypeError):
        return None


def _parse_int(s: str | None) -> int | None:
    if s is None or s == "":
        return None
    try:
        return int(str(s).replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (ValueError, AttributeError):
        return None


@dataclass
class ListedMonthlyRevenueResponse:
    """Listed-company monthly revenue feed — one row per company per publish."""

    rows: list[MonthlyRevenueRow] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: list[dict] | None) -> "ListedMonthlyRevenueResponse":
        rows: list[MonthlyRevenueRow] = []
        for raw in data or []:
            ym = _from_roc_yyyymm(raw.get("資料年月"))
            if ym is None:
                continue
            curr = _parse_int(raw.get("營業收入-當月營收"))
            if curr is None:
                continue
            rows.append(
                MonthlyRevenueRow(
                    company_code=(raw.get("公司代號") or "").strip(),
                    company_name=(raw.get("公司名稱") or "").strip(),
                    industry=(raw.get("產業別") or "").strip(),
                    year=ym[0],
                    month=ym[1],
                    revenue_curr_thousands=curr,
                    revenue_prior_thousands=_parse_int(raw.get("營業收入-上月營收")),
                    revenue_lastyear_thousands=_parse_int(raw.get("營業收入-去年當月營收")),
                    ytd_revenue_thousands=_parse_int(raw.get("累計營業收入-當月累計營收")),
                    ytd_lastyear_thousands=_parse_int(raw.get("累計營業收入-去年累計營收")),
                    mom_pct=_parse_float(raw.get("營業收入-上月比較增減(%)")),
                    yoy_pct=_parse_float(raw.get("營業收入-去年同月增減(%)")),
                    ytd_yoy_pct=_parse_float(raw.get("累計營業收入-前期比較增減(%)")),
                    publish_date=_from_roc_yyyymmdd(raw.get("出表日期")),
                )
            )
        return cls(rows=rows)

    def by_code(self, company_code: str) -> MonthlyRevenueRow | None:
        for r in self.rows:
            if r.company_code == company_code:
                return r
        return None

    def to_output(self) -> str:
        return f"TWSE monthly revenue feed: {len(self.rows)} companies reported"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# 1h cache. New data appears once a month around the 10th and gets refreshed
# as more companies report; an hour is short enough to catch the morning flip
# on release day, long enough to avoid hammering the feed.
LISTED_MONTHLY_REVENUE = Endpoint(
    "/v1/opendata/t187ap05_L",
    cache_ttl=3600,
    response_model=ListedMonthlyRevenueResponse,
)
