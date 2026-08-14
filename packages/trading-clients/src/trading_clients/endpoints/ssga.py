"""SSGA (SPDR) ETF daily-holdings endpoint — the free single-name bond mark.

There is no free CUSIP-level corporate bond price feed. FINRA's TRACE detail is
a paid tier, iShares' holdings endpoint returns its SPA shell, and every vendor
API (Finnhub, FMP, cbonds) walls bonds behind a premium plan. What *is* free and
timestamped is the daily holdings file every bond ETF publishes for
transparency: an issuer's bonds appear there with par value and market value,
and the ratio is the pricing service's clean price.

That makes coverage a function of which funds hold the name, so callers query a
**panel** (`CORPORATE_BOND_FUNDS`) and take the union. A bond no US SPDR fund
holds — a euro tranche, an off-index private placement — will not appear at all,
which is a coverage gap to report rather than an error to raise.

What these marks are, stated plainly: **T+1 pricing-service valuations, not
trade prints.** An ETF strikes NAV off an evaluated price, which for a thinly
traded high-yield bond may be a matrix estimate rather than an executed level.
Good enough to track a spread trend; not a quote you could hit.

The workbook carries a preamble (fund name, ticker, "As of" date) above the
header row, so parsing locates the header by its `Name` cell rather than
assuming a fixed offset, then maps columns by title — SSGA has reordered them
before.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import openpyxl

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest
from trading_clients.table_helpers import md_table

# SPDR corporate-credit ETFs whose holdings union covers the investment-grade
# and high-yield curves. Short/intermediate/long IG plus broad and short HY —
# an issuer's bonds are spread across these by maturity and rating, so a
# single-fund lookup misses most of a curve.
CORPORATE_BOND_FUNDS: tuple[tuple[str, str], ...] = (
    ("JNK", "High Yield"),
    ("SJNK", "Short Term High Yield"),
    ("SPBO", "IG Corporate"),
    ("SPIB", "IG Intermediate"),
    ("SPSB", "IG Short Term"),
    ("SPLB", "IG Long Term"),
)

BASE_URL = "https://www.ssga.com"

_ASOF_RE = re.compile(r"As of\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", re.IGNORECASE)

# Header titles we care about, normalized to lowercase.
_COL_ALIASES: dict[str, str] = {
    "name": "name",
    "identifier": "identifier",
    "sedol": "sedol",
    "weight": "weight",
    "coupon": "coupon",
    "par value": "par_value",
    "market value": "market_value",
    "local currency": "currency",
    "maturity": "maturity",
}


def _parse_maturity(raw: object) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _cell(row: tuple, colmap: dict[str, int], key: str) -> object:
    """Value at the column `key` maps to, or None if absent/short row."""
    idx = colmap.get(key)
    return row[idx] if idx is not None and idx < len(row) else None


def _to_float(raw: object) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class HoldingsRequest(PathRequest, ParamsRequest):
    """Daily holdings for one SPDR fund. `ticker` is case-insensitive; the URL
    wants it lowercase."""

    ticker: str

    def to_path_params(self) -> dict[str, str]:
        return {"ticker": self.ticker.strip().lower()}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class SsgaHolding:
    name: str
    identifier: str
    weight_pct: float | None = None
    coupon_pct: float | None = None
    par_value: float | None = None
    market_value: float | None = None
    currency: str | None = None
    maturity: date | None = None
    sedol: str | None = None

    @property
    def is_priceable_bond(self) -> bool:
        """Has everything the yield math needs. Cash lines, futures, and
        derivative overlays all fail this and are meant to be skipped."""
        return bool(
            self.coupon_pct is not None
            and self.maturity is not None
            and self.par_value
            and self.market_value
        )


@dataclass
class SsgaHoldingsResponse:
    """One fund's holdings file, with the publisher's own as-of date.

    `as_of` is load-bearing — it is the only thing that dates the marks, and a
    stale file (holiday, publishing delay) is the failure mode most likely to
    go unnoticed.
    """

    fund_name: str = ""
    fund_ticker: str = ""
    as_of: date | None = None
    holdings: list[SsgaHolding] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: bytes) -> SsgaHoldingsResponse:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.active
        if ws is None:
            return cls()

        fund_name = ""
        fund_ticker = ""
        as_of: date | None = None
        colmap: dict[str, int] = {}
        holdings: list[SsgaHolding] = []

        for row in ws.iter_rows(values_only=True):
            if not row:
                continue
            first = row[0]

            if not colmap:
                # Preamble: labelled key/value rows, then the header row.
                if isinstance(first, str):
                    label = first.strip().rstrip(":").lower()
                    if label == "fund name" and len(row) > 1:
                        fund_name = str(row[1] or "")
                        continue
                    if label == "ticker symbol" and len(row) > 1:
                        fund_ticker = str(row[1] or "")
                        continue
                    if label == "holdings" and len(row) > 1:
                        m = _ASOF_RE.search(str(row[1] or ""))
                        if m:
                            try:
                                as_of = datetime.strptime(m.group(1), "%d-%b-%Y").date()
                            except ValueError:
                                as_of = None
                        continue
                    if label == "name":
                        for idx, cell in enumerate(row):
                            if isinstance(cell, str):
                                key = _COL_ALIASES.get(cell.strip().lower())
                                if key:
                                    colmap[key] = idx
                        continue
                continue

            name = _cell(row, colmap, "name")
            identifier = _cell(row, colmap, "identifier")
            if not name or not identifier:
                continue

            currency = _cell(row, colmap, "currency")
            sedol = _cell(row, colmap, "sedol")
            holdings.append(
                SsgaHolding(
                    name=str(name).strip(),
                    identifier=str(identifier).strip(),
                    weight_pct=_to_float(_cell(row, colmap, "weight")),
                    coupon_pct=_to_float(_cell(row, colmap, "coupon")),
                    par_value=_to_float(_cell(row, colmap, "par_value")),
                    market_value=_to_float(_cell(row, colmap, "market_value")),
                    currency=str(currency).strip() if currency else None,
                    maturity=_parse_maturity(_cell(row, colmap, "maturity")),
                    sedol=str(sedol).strip() if sedol else None,
                )
            )

        wb.close()
        return cls(
            fund_name=fund_name,
            fund_ticker=fund_ticker,
            as_of=as_of,
            holdings=holdings,
        )

    def matching(self, needles: list[str]) -> list[SsgaHolding]:
        """Priceable bonds whose name starts with any of `needles`.

        Prefix rather than substring: holdings names lead with the issuer
        (`COREWEAVE INC COMPANY GUAR 144A 10/31 9.75`), and a substring match on
        a short issuer name pulls in unrelated obligors that merely mention it.
        """
        wants = [n.strip().upper() for n in needles if n and n.strip()]
        if not wants:
            return []
        return [
            h
            for h in self.holdings
            if h.is_priceable_bond and any(h.name.upper().startswith(w) for w in wants)
        ]

    def to_output(self) -> str:
        if not self.holdings:
            return "(no holdings)"
        head = f"{self.fund_ticker or '?'} — {self.fund_name or '?'}"
        if self.as_of:
            head += f" (as of {self.as_of.isoformat()})"
        rows = [
            [
                h.name,
                h.identifier,
                f"{h.coupon_pct:g}%" if h.coupon_pct is not None else "",
                h.maturity.isoformat() if h.maturity else "",
                f"{h.weight_pct:.4f}" if h.weight_pct is not None else "",
            ]
            for h in self.holdings[:50]
        ]
        table = md_table(["Name", "ISIN", "Coupon", "Maturity", "Weight %"], rows)
        suffix = f"\n\n_{len(self.holdings)} holdings total_" if len(self.holdings) > 50 else ""
        return f"{head}\n\n{table}{suffix}"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# 6h: the file is published once daily, and a briefing → review session can
# hit the same panel twice within minutes.
HOLDINGS = Endpoint(
    "/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx",
    cache_ttl=21600,
    response_model=SsgaHoldingsResponse,
)
