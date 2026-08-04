"""Free-cash-flow margin: the capital-intensity read behind a growth thesis.

FCF margin = (Operating Cash Flow - Capex) / Revenue, per fiscal period.

Two choices decide what the number means, so both are reported rather than
picked for the caller:

**Window.** A single quarter is noisy — one working-capital build or a lumpy
capex step halves it without anything changing in the business. TTM is the
basis for a thesis-exit trigger; the per-quarter series is the early warning.

**Stock comp.** Standard FCF (what issuers report) leaves SBC added back, since
it is non-cash and sits inside operating cash flow. For heavy-SBC semis and
software that add-back can be a third of reported FCF, so an ex-SBC variant
runs alongside as the harsher owner-earnings read.

Pure computation; the MCP tool fetches Finnhub's reported financials and passes
the numeric income and cash-flow rows here.

**Finnhub's "quarterly" feed is year-to-date cumulative, not discrete.** A 10-Q
tags both the three-month and the year-to-date duration, and the extracted value
is the YTD one: Q1 is a real quarter, Q2 is six months, Q3 is nine months, and Q4
never appears — it exists only inside the 10-K. Summing those rows for a TTM
double-counts revenue and produces a confidently wrong margin, so `to_discrete`
de-cumulates within each fiscal year and derives Q4 as (annual − nine-month).
"""

from dataclasses import dataclass
from typing import Any

from trading_clients.table_helpers import fmt_large, fmt_number, kv_table, list_table

# Percentage points of TTM-margin change before a trend is called a direction
# rather than noise. TTM already smooths the quarter, so 1pp is a real move.
_TREND_BAND_PP = 1.0

_QUARTERS_PER_YEAR = 4

# Period flows that de-cumulate by subtraction. All are durations, so the
# discrete quarter is always (this YTD - prior YTD). A balance-sheet level would
# not behave this way, which is why the list is explicit rather than "every key" —
# only pass income-statement and cash-flow rows to to_discrete, never balance sheet.
#
# EPS is deliberately absent: per-share figures don't difference cleanly because
# the diluted share count moves between periods. A dropped key reads as absent
# downstream, which is the safe failure; a differenced one would read as precise.
_FLOW_FIELDS = (
    # income-statement durations
    "Revenue",
    "Cost of Revenue",
    "Gross Profit",
    "Operating Income",
    "Net Income",
    # cash-flow durations
    "Operating CF",
    "Capex",
    "Investing CF",
    "Dividends",
    "Buybacks",
    "Financing CF",
    "Stock Comp",
)


def _period_key(row: dict[str, Any]) -> tuple:
    """Join key for pairing an income row with its cash-flow row.

    Fiscal year+quarter when present, else the period end-date. Never the list
    index: income and cash-flow rows are fetched with different limits and one
    section can lag the other, so positional pairing silently divides this
    quarter's cash flow by last quarter's revenue.
    """
    fy, fq = row.get("fiscal_year"), row.get("fiscal_quarter")
    if fy is not None and fq is not None:
        return ("fq", fy, fq)
    return ("period", row.get("period", ""))


def _diff_row(
    cur: dict[str, Any], prior: dict[str, Any], fiscal_quarter: int | None = None
) -> dict[str, Any]:
    """Subtract a prior cumulative row from the current one to get a discrete period.

    A flow is None whenever either side is missing: carrying the cumulative value
    through would silently present nine months of cash flow as one quarter.
    """
    out: dict[str, Any] = {
        "period": cur.get("period", ""),
        "form": cur.get("form", ""),
        "fiscal_year": cur.get("fiscal_year"),
        "fiscal_quarter": fiscal_quarter
        if fiscal_quarter is not None
        else cur.get("fiscal_quarter"),
    }
    for field in _FLOW_FIELDS:
        a, b = cur.get(field), prior.get(field)
        out[field] = None if a is None or b is None else a - b
    return out


def to_discrete(
    quarterly_rows: list[dict[str, Any]], annual_rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Turn Finnhub's YTD-cumulative 10-Q rows into discrete fiscal quarters.

    Q1 passes through. Q2 and Q3 are differenced against the prior quarter in the
    same fiscal year. Q4 is derived as (10-K annual − Q3 nine-month) when the
    annual feed is supplied. Quarters whose predecessor is missing are dropped
    rather than emitted as cumulative values wearing a quarterly label.
    """
    by_year: dict[int, dict[int, dict[str, Any]]] = {}
    for row in quarterly_rows:
        fy, fq = row.get("fiscal_year"), row.get("fiscal_quarter")
        if fy is None or fq is None:
            continue
        by_year.setdefault(fy, {}).setdefault(fq, row)

    annual_by_year: dict[int, dict[str, Any]] = {}
    for row in annual_rows or []:
        fy = row.get("fiscal_year")
        if fy is not None:
            annual_by_year.setdefault(fy, row)

    out: list[dict[str, Any]] = []
    for fy, quarters in by_year.items():
        for fq, row in quarters.items():
            if fq == 1:
                out.append({**row, "fiscal_quarter": 1})
            elif (prior := quarters.get(fq - 1)) is not None:
                out.append(_diff_row(row, prior))
        q3, annual = quarters.get(3), annual_by_year.get(fy)
        if q3 is not None and annual is not None:
            out.append(_diff_row(annual, q3, fiscal_quarter=4))

    out.sort(key=lambda r: (r.get("fiscal_year") or 0, r.get("fiscal_quarter") or 0), reverse=True)
    return out


def _prev_quarter(fiscal_year: int, fiscal_quarter: int) -> tuple[int, int]:
    return (fiscal_year - 1, 4) if fiscal_quarter == 1 else (fiscal_year, fiscal_quarter - 1)


def _outflow(val: float | None) -> float | None:
    """Normalize a cash outflow to a positive magnitude.

    Capex and SBC are reported positive under XBRL convention but negative in
    some filers' presentation. Taking the magnitude means a sign flip upstream
    can't turn a subtraction into an addition and inflate FCF.
    """
    return None if val is None else abs(val)


@dataclass(frozen=True)
class FcfPeriod:
    """One fiscal period's FCF inputs and derived margins."""

    period: str
    fiscal_year: int | None
    fiscal_quarter: int | None
    revenue: float | None
    operating_cf: float | None
    capex: float | None
    stock_comp: float | None

    @property
    def fcf(self) -> float | None:
        if self.operating_cf is None:
            return None
        return self.operating_cf - (self.capex or 0.0)

    @property
    def fcf_ex_sbc(self) -> float | None:
        if self.fcf is None or self.stock_comp is None:
            return None
        return self.fcf - self.stock_comp

    @property
    def margin_pct(self) -> float | None:
        if self.fcf is None or not self.revenue:
            return None
        return self.fcf / self.revenue * 100

    @property
    def margin_ex_sbc_pct(self) -> float | None:
        if self.fcf_ex_sbc is None or not self.revenue:
            return None
        return self.fcf_ex_sbc / self.revenue * 100

    @property
    def usable(self) -> bool:
        return self.fcf is not None and bool(self.revenue)


@dataclass(frozen=True)
class WindowMargin:
    """Aggregate FCF margin over a window of periods (sum of parts, not a mean
    of ratios — a mean of quarterly margins over-weights small-revenue quarters).
    """

    n_periods: int
    revenue: float
    fcf: float
    fcf_ex_sbc: float | None
    contiguous: bool

    @property
    def is_full_year(self) -> bool:
        """A window is only a true TTM at four consecutive quarters."""
        return self.n_periods == _QUARTERS_PER_YEAR and self.contiguous

    @property
    def margin_pct(self) -> float | None:
        return self.fcf / self.revenue * 100 if self.revenue else None

    @property
    def margin_ex_sbc_pct(self) -> float | None:
        if self.fcf_ex_sbc is None or not self.revenue:
            return None
        return self.fcf_ex_sbc / self.revenue * 100


def build_series(
    income_rows: list[dict[str, Any]], cf_rows: list[dict[str, Any]]
) -> list[FcfPeriod]:
    """Pair income and cash-flow rows by fiscal period, most recent first."""
    cf_by_key: dict[tuple, dict[str, Any]] = {}
    for row in cf_rows:
        cf_by_key.setdefault(_period_key(row), row)

    periods: list[FcfPeriod] = []
    for inc in income_rows:
        cf = cf_by_key.get(_period_key(inc), {})
        periods.append(
            FcfPeriod(
                period=inc.get("period", ""),
                fiscal_year=inc.get("fiscal_year"),
                fiscal_quarter=inc.get("fiscal_quarter"),
                revenue=inc.get("Revenue"),
                operating_cf=cf.get("Operating CF"),
                capex=_outflow(cf.get("Capex")),
                stock_comp=_outflow(cf.get("Stock Comp")),
            )
        )
    return periods


def aggregate(periods: list[FcfPeriod]) -> WindowMargin | None:
    """Sum a window into one margin. Returns None when nothing is usable.

    The ex-SBC total is None unless *every* period in the window reports stock
    comp — a partial sum would understate the deduction and read as a better
    number than the truth.
    """
    usable = [p for p in periods if p.usable]
    if not usable:
        return None
    ex_sbc: float | None = None
    if all(p.fcf_ex_sbc is not None for p in usable):
        ex_sbc = sum(p.fcf_ex_sbc for p in usable if p.fcf_ex_sbc is not None)
    return WindowMargin(
        n_periods=len(usable),
        revenue=sum(p.revenue for p in usable if p.revenue),
        fcf=sum(p.fcf for p in usable if p.fcf is not None),
        fcf_ex_sbc=ex_sbc,
        contiguous=is_contiguous(usable),
    )


def is_contiguous(periods: list[FcfPeriod]) -> bool:
    """True when the periods are consecutive fiscal quarters, most recent first.

    A gap (a fiscal year whose Q4 could not be derived) makes a four-row window
    span more than a year, which would understate the margin's denominator.
    """
    for cur, nxt in zip(periods, periods[1:], strict=False):
        if cur.fiscal_year is None or cur.fiscal_quarter is None:
            return False
        if (nxt.fiscal_year, nxt.fiscal_quarter) != _prev_quarter(
            cur.fiscal_year, cur.fiscal_quarter
        ):
            return False
    return True


def classify_trend(current: float | None, prior: float | None) -> str:
    """Direction of the TTM margin against the prior TTM window."""
    if current is None or prior is None:
        return "N/A"
    delta = current - prior
    if delta > _TREND_BAND_PP:
        return "Expanding"
    if delta < -_TREND_BAND_PP:
        return "Compressing"
    return "Stable"


def year_ago(periods: list[FcfPeriod], target: FcfPeriod) -> FcfPeriod | None:
    """Same fiscal quarter, one year back — the like-for-like seasonal compare."""
    if target.fiscal_year is None or target.fiscal_quarter is None:
        return None
    for p in periods:
        if p.fiscal_quarter == target.fiscal_quarter and p.fiscal_year == target.fiscal_year - 1:
            return p
    return None


@dataclass(frozen=True)
class FcfMarginReport:
    symbol: str
    threshold_pct: float
    periods: list[FcfPeriod]
    ttm: WindowMargin | None
    prior_ttm: WindowMargin | None

    @property
    def latest(self) -> FcfPeriod | None:
        return next((p for p in self.periods if p.usable), None)

    @property
    def trend(self) -> str:
        """Only compare like windows — a partial window vs a full year is not a trend."""
        if not (self.ttm and self.ttm.is_full_year):
            return "N/A"
        if not (self.prior_ttm and self.prior_ttm.is_full_year):
            return "N/A"
        return classify_trend(self.ttm.margin_pct, self.prior_ttm.margin_pct)

    def _pct(self, val: float | None) -> str:
        return f"{fmt_number(val, 1)}%" if val is not None else "n/a"

    def _verdict(self) -> str:
        """The trigger call, stated on TTM with the quarter shown separately.

        A thesis-exit trigger evaluated on one quarter fires on working-capital
        noise, so TTM is the binding basis and the quarter is the early warning.
        """
        ttm_pct = self.ttm.margin_pct if self.ttm else None
        q_pct = self.latest.margin_pct if self.latest else None
        if ttm_pct is None or self.ttm is None:
            return "**Trigger: N/A** — insufficient data to compute a TTM margin."
        if not self.ttm.is_full_year:
            return (
                f"**Trigger: N/A** — only {self.ttm.n_periods} usable "
                f"{'consecutive ' if self.ttm.contiguous else ''}quarter(s) available; "
                f"a TTM margin needs four consecutive. Window margin {self._pct(ttm_pct)} "
                f"is shown for reference only, not as a trigger basis."
            )

        thresh = f"{fmt_number(self.threshold_pct, 0)}%"
        ttm_txt = self._pct(ttm_pct)
        q_txt = self._pct(q_pct)
        ttm_breach = ttm_pct < self.threshold_pct
        q_breach = q_pct is not None and q_pct < self.threshold_pct

        if ttm_breach:
            return (
                f"**Trigger: BREACHED** — TTM {ttm_txt} is below {thresh} (latest quarter {q_txt})."
            )
        if q_breach:
            return (
                f"**Trigger: intact — EARLY WARNING** — TTM {ttm_txt} holds above "
                f"{thresh}, but the latest quarter fell to {q_txt}. One quarter is "
                f"working-capital and capex noise; it is the watch item, not the exit."
            )
        return (
            f"**Trigger: intact** — TTM {ttm_txt} and latest quarter {q_txt} both above {thresh}."
        )

    def to_output(self) -> str:
        if not self.ttm and not any(p.usable for p in self.periods):
            return f"(no FCF margin data for {self.symbol} — missing revenue or cash-flow rows)"

        latest = self.latest
        prior_yr = year_ago(self.periods, latest) if latest else None

        summary: dict[str, Any] = {"Symbol": self.symbol}
        if latest:
            summary["Latest Period"] = latest.period
            summary["Latest Qtr Margin"] = self._pct(latest.margin_pct)
            if prior_yr:
                summary["Year-Ago Qtr Margin"] = self._pct(prior_yr.margin_pct)
        if self.ttm:
            label = "TTM Margin" if self.ttm.is_full_year else f"Window ({self.ttm.n_periods}q)"
            summary[label] = self._pct(self.ttm.margin_pct)
            summary[f"{label} ex-SBC"] = self._pct(self.ttm.margin_ex_sbc_pct)
        if self.prior_ttm and self.prior_ttm.is_full_year:
            summary["Prior TTM Margin"] = self._pct(self.prior_ttm.margin_pct)
        summary["TTM Trend"] = self.trend

        rows = [
            {
                "Period": p.period,
                "Revenue": fmt_large(p.revenue),
                "Op CF": fmt_large(p.operating_cf),
                "Capex": fmt_large(p.capex),
                "FCF": fmt_large(p.fcf),
                "Margin": self._pct(p.margin_pct),
                "Margin ex-SBC": self._pct(p.margin_ex_sbc_pct),
            }
            for p in self.periods
        ]

        parts = [
            f"## FCF Margin — {self.symbol}",
            "",
            kv_table(summary),
            "",
            self._verdict(),
            "",
            "### Per-period detail",
            "",
            list_table(rows),
            "",
            "_FCF = Operating CF − Capex. ex-SBC additionally subtracts stock "
            "compensation, which standard FCF adds back as non-cash. Quarters are "
            "de-cumulated from the YTD figures a 10-Q reports; Q4 is derived as "
            "(10-K annual − nine-month). Sourced from filed 10-Q/10-K only — an "
            "earnings 8-K released before its 10-Q is not yet reflected here._",
        ]
        return "\n".join(parts)


def analyze(
    symbol: str,
    quarterly_income: list[dict[str, Any]],
    quarterly_cf: list[dict[str, Any]],
    annual_income: list[dict[str, Any]] | None = None,
    annual_cf: list[dict[str, Any]] | None = None,
    threshold_pct: float = 15.0,
) -> FcfMarginReport:
    """Build the full FCF-margin read: per-quarter series, TTM, prior TTM, trend.

    Takes Finnhub's cumulative quarterly rows plus (optionally) the annual rows
    that let Q4 be derived. Without the annual feed every fiscal year is missing
    its Q4, so no four-quarter window is contiguous and no TTM is reported.
    """
    periods = build_series(
        to_discrete(quarterly_income, annual_income),
        to_discrete(quarterly_cf, annual_cf),
    )
    return FcfMarginReport(
        symbol=symbol.upper(),
        threshold_pct=threshold_pct,
        periods=periods,
        ttm=aggregate(periods[:_QUARTERS_PER_YEAR]),
        prior_ttm=aggregate(periods[_QUARTERS_PER_YEAR : _QUARTERS_PER_YEAR * 2]),
    )
