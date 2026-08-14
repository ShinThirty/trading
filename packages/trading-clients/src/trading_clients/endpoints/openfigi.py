"""OpenFIGI endpoint definitions — issuer bond-universe discovery.

OpenFIGI maps identifiers to FIGIs. We use exactly one thing from it: given an
equity ticker, *what bonds does this issuer have outstanding* — including the
144A / RegS / euro tranches and the ones no US ETF holds. It carries no prices,
so it is the universe half of the credit read; SSGA supplies the marks.

The bond's economics arrive encoded in the Bloomberg-style `ticker` string
(`CRWV 9.75 10/01/31 144A`) rather than as fields, so `parse_bond_ticker` pulls
coupon and maturity back out. Rows that don't parse as a coupon bond are dropped
— the same search returns term loans (`CRWV L 11/09/29 FA`) and perpetuals
(`CORWEA L PERP FA`), which have no maturity to compute a yield to.

Anonymous access is rate-limited to 5 search requests/minute, which is why the
endpoint caches for a day: an issuer's bond *universe* changes on new issuance,
not intraday.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint
from trading_clients.table_helpers import md_table

# `CRWV 9.75 10/01/31 144A` / `ORCL 6 1/2 04/15/38` / `T 3.55 09/15/55`.
# Coupon is decimal or mixed-fraction; the trailing token is a placement
# qualifier (144A, REGS, EMTN, ...) and is optional.
_BOND_TICKER_RE = re.compile(
    r"^(?P<issuer>[A-Z0-9]+)\s+"
    r"(?P<coupon>\d+(?:\.\d+)?(?:\s+\d+/\d+)?)\s+"
    r"(?P<maturity>\d{2}/\d{2}/\d{2})"
    r"(?:\s+(?P<qualifier>.+))?$"
)

# Two-digit years below this pivot are 20xx. Bonds maturing 2080+ are rare
# enough that resolving 80-99 to the 1900s (already-matured paper that lingers
# in reference data) is the safer default.
_CENTURY_PIVOT = 80


def _parse_coupon(raw: str) -> float | None:
    """Parse `9.75` or `6 1/2` into a float percent."""
    raw = raw.strip()
    if " " in raw:
        whole, frac = raw.split(None, 1)
        num, _, den = frac.partition("/")
        try:
            return float(whole) + float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_bond_ticker(ticker: str) -> tuple[str, float, date] | None:
    """Extract (issuer prefix, coupon percent, maturity) from a bond ticker.

    Returns None for anything that isn't a dated coupon bond — loans, perpetuals,
    and malformed rows all land here and are meant to be filtered out.
    """
    m = _BOND_TICKER_RE.match(ticker.strip())
    if not m:
        return None
    coupon = _parse_coupon(m.group("coupon"))
    if coupon is None:
        return None
    mm, dd, yy = m.group("maturity").split("/")
    try:
        year = int(yy)
        year += 2000 if year < _CENTURY_PIVOT else 1900
        maturity = date(year, int(mm), int(dd))
    except ValueError:
        return None
    return m.group("issuer"), coupon, maturity


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class BondSearchRequest(BodyRequest):
    """Full-text search over the Corp market sector.

    `query` is normally the issuer's equity ticker — bond tickers carry it as
    their first token, which makes it a precise join key.
    """

    query: str
    start: str | None = None

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"query": self.query, "marketSecDes": "Corp"}
        if self.start:
            body["start"] = self.start
        return body


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class OpenFigiBond:
    figi: str
    issuer_name: str
    ticker: str
    issuer_prefix: str
    coupon_pct: float
    maturity: date
    security_type: str | None = None
    exch_code: str | None = None
    qualifier: str | None = None

    @property
    def is_144a(self) -> bool:
        """144A private placement — the channel speculative issuers fund through."""
        return (self.qualifier or "").upper().startswith("144A") or (
            self.security_type or ""
        ).upper() == "PRIV PLACEMENT"

    @property
    def trace_reported(self) -> bool:
        """Reported to TRACE, i.e. a US-registered/144A bond rather than a euro tranche."""
        return (self.exch_code or "").upper() == "TRACE"


@dataclass
class BondSearchResponse:
    """Coupon bonds returned for a Corp-sector search, newest maturity last.

    `next_cursor` is OpenFIGI's pagination token; a non-empty value means the
    universe was truncated at one page.
    """

    bonds: list[OpenFigiBond] = field(default_factory=list)
    next_cursor: str | None = None

    @classmethod
    def from_response(cls, data: dict) -> BondSearchResponse:
        rows = (data or {}).get("data") or []
        bonds: list[OpenFigiBond] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = row.get("ticker") or ""
            parsed = parse_bond_ticker(ticker)
            if parsed is None:
                continue
            issuer_prefix, coupon, maturity = parsed
            m = _BOND_TICKER_RE.match(ticker.strip())
            bonds.append(
                OpenFigiBond(
                    figi=row.get("figi") or "",
                    issuer_name=row.get("name") or "",
                    ticker=ticker,
                    issuer_prefix=issuer_prefix,
                    coupon_pct=coupon,
                    maturity=maturity,
                    security_type=row.get("securityType"),
                    exch_code=row.get("exchCode"),
                    qualifier=m.group("qualifier") if m else None,
                )
            )
        bonds.sort(key=lambda b: b.maturity)
        return cls(bonds=bonds, next_cursor=(data or {}).get("next"))

    def for_issuer(self, prefix: str) -> list[OpenFigiBond]:
        """Bonds whose ticker prefix matches `prefix` exactly (case-insensitive).

        A bare full-text search pulls in unrelated issuers whose names happen to
        share a word; matching on the ticker's first token removes them.
        """
        want = prefix.strip().upper()
        return [b for b in self.bonds if b.issuer_prefix.upper() == want]

    def live(self, asof: date, prefix: str | None = None) -> list[OpenFigiBond]:
        """Bonds not yet matured as of `asof`, optionally filtered to one issuer.

        Reference data retains bonds indefinitely — a search for ORCL still
        returns 2001 paper — so anything downstream that counts an issuer's debt
        has to drop the dead ones first.
        """
        pool = self.for_issuer(prefix) if prefix else self.bonds
        return [b for b in pool if b.maturity > asof]

    def issuer_names(self, prefix: str | None = None) -> list[str]:
        """Distinct issuer legal names, most common first — the join key into a
        holdings file, which carries names rather than tickers.

        Pass `prefix` (the equity ticker) to scope this to the right obligor. A
        bare full-text search collides badly: searching "IREN" returns both IREN
        Ltd and the unrelated Italian utility IREN SpA, and the utility has more
        bonds, so an unfiltered count picks the wrong company outright.
        """
        pool = self.for_issuer(prefix) if prefix else self.bonds
        counts: dict[str, int] = {}
        for b in pool:
            if b.issuer_name:
                counts[b.issuer_name] = counts.get(b.issuer_name, 0) + 1
        return sorted(counts, key=lambda n: -counts[n])

    def to_output(self) -> str:
        if not self.bonds:
            return "(no bonds found)"
        rows = [
            [
                b.ticker,
                b.issuer_name,
                f"{b.coupon_pct:g}%",
                b.maturity.isoformat(),
                "144A" if b.is_144a else (b.security_type or ""),
            ]
            for b in self.bonds
        ]
        out = md_table(["Ticker", "Issuer", "Coupon", "Maturity", "Type"], rows)
        if self.next_cursor:
            out += "\n\n_(truncated — more results available)_"
        return out


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# A day: an issuer's outstanding bond list changes on new issuance, and the
# anonymous search quota (5/min) makes re-fetching expensive.
SEARCH = Endpoint(
    "/v3/search",
    cache_ttl=86400,
    response_model=BondSearchResponse,
)
