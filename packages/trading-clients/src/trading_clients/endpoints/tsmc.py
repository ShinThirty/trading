"""TSMC monthly revenue endpoint definitions.

TSMC publishes consolidated monthly revenue (in NT$ millions) on the 10th of
each month at https://investor.tsmc.com/english/monthly-revenue/{year}. The
HTML table is static — twelve rows per year (Jan-Dec), with empty cells for
months that haven't been reported yet.

This is one of the cleanest leading indicators for the global semi cycle:
TSMC is the foundry layer underneath every advanced AI accelerator, so a
positive YoY surprise on a release morning often pre-prints upside in the
broader semi tape (NVDA, AMD, AVGO, MRVL, ASML, AMAT) before any of those
names report.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest
from trading_clients.table_helpers import md_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class GetMonthlyRevenueRequest(PathRequest, ParamsRequest):
    year: int

    def to_path_params(self) -> dict[str, str]:
        return {"year": str(self.year)}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════

_MONTH_LABELS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip


@dataclass(frozen=True)
class MonthlyRevenue:
    """One row of TSMC's consolidated monthly revenue table.

    revenue_ntd_m and yoy_pct are None for months that haven't reported yet
    (the table renders future months with empty cells)."""

    year: int
    month: int  # 1-12
    revenue_ntd_m: float | None
    yoy_pct: float | None


class _RevenueTableParser(HTMLParser):
    """Pulls (month_label, revenue_text, yoy_text) triples out of TSMC's
    `basicTable` monthly-revenue table.

    The page contains exactly one table whose first body row carries
    "Net Revenue" / "YoY Change" headers; data rows are 3-cell rows where
    cell 0 is a month abbreviation (Jan., Feb., ...) and cells 1-2 are the
    revenue and YoY columns. Aggregate / Total rows are skipped — only month
    rows survive the _MONTH_LABELS filter in `_parse_rows`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_target_table = False
        self._table_depth = 0
        self._row: list[str] = []
        self._cell_parts: list[str] | None = None
        self._in_cell = False
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "table":
            cls = (attrs_d.get("class") or "").lower()
            if "basictable" in cls and not self._in_target_table:
                self._in_target_table = True
            if self._in_target_table:
                self._table_depth += 1
        elif tag == "tr" and self._in_target_table:
            self._row = []
        elif tag in ("td", "th") and self._in_target_table:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_target_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_target_table = False
        elif tag == "tr" and self._in_target_table and self._row:
            self.rows.append(self._row)
            self._row = []
        elif tag in ("td", "th") and self._in_target_table and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._cell_parts or [])).strip()
            self._row.append(text)
            self._in_cell = False
            self._cell_parts = None

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cell_parts is not None:
            self._cell_parts.append(data)


def _parse_revenue(text: str) -> float | None:
    """'401,255' → 401255.0; '' / '-' → None."""
    if not text or text in ("-", "—"):
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_yoy(text: str) -> float | None:
    """'36.8%' → 36.8; '-12.3%' → -12.3; '' → None."""
    if not text:
        return None
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*%$", text.strip())
    return float(m.group(1)) if m else None


def _month_from_label(label: str) -> int | None:
    """'Jan.', 'February', 'JUL' → 1, 2, 7. Returns None for non-month rows."""
    key = re.sub(r"[^a-z]", "", label.lower())[:3]
    return _MONTH_LABELS.get(key)


@dataclass
class MonthlyRevenueResponse:
    """One year of TSMC consolidated monthly revenue.

    The year is recovered from the `<link rel="canonical">` tag in the page
    head — the URL shape is always `/english/monthly-revenue/{year}`.
    """

    year: int
    rows: list[MonthlyRevenue] = field(default_factory=list)

    @classmethod
    def from_response(cls, html: str) -> "MonthlyRevenueResponse":
        year_match = re.search(r"/english/monthly-revenue/(\d{4})", html or "")
        year = int(year_match.group(1)) if year_match else 0

        parser = _RevenueTableParser()
        parser.feed(html or "")

        rows: list[MonthlyRevenue] = []
        for raw in parser.rows:
            if len(raw) != 3:
                continue
            month = _month_from_label(raw[0])
            if month is None:
                continue
            rows.append(
                MonthlyRevenue(
                    year=year,
                    month=month,
                    revenue_ntd_m=_parse_revenue(raw[1]),
                    yoy_pct=_parse_yoy(raw[2]),
                )
            )
        rows.sort(key=lambda r: r.month)
        return cls(year=year, rows=rows)

    def to_output(self) -> str:
        """Year-only markdown table. The MCP tool layer is expected to stitch
        multiple years together and compute MoM; this output is mainly useful
        for one-off debug/inspection of a single year's parse."""
        if not self.rows:
            return f"(no data for {self.year})"
        body = [
            [
                f"{r.year}-{r.month:02d}",
                f"{r.revenue_ntd_m:,.0f}" if r.revenue_ntd_m is not None else "—",
                f"{r.yoy_pct:+.1f}%" if r.yoy_pct is not None else "—",
            ]
            for r in self.rows
        ]
        return md_table(["Month", "Revenue (NT$M)", "YoY"], body)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# 1h cache. New rows appear once a month around the 10th; an hour is short
# enough to catch the morning flip if the briefing runs twice on release day,
# and long enough to avoid pounding TSMC's static-page server.
MONTHLY_REVENUE = Endpoint(
    "/english/monthly-revenue/{year}",
    cache_ttl=3600,
    response_model=MonthlyRevenueResponse,
)
