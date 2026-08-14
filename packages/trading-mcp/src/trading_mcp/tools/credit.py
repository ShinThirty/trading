"""Corporate credit tools — single-name spreads and market-wide breadth.

Two reads that answer different questions, deliberately kept as separate tools:

`get_issuer_credit` — what does *this borrower's* own paper yield, and how does
that compare to its rating cohort? The bear case on a debt-funded issuer converges
through refinancing, so the spread on its outstanding bonds is the mechanism, and
an equity that rallies while its own credit widens is a disconnect the standard
price-vs-consensus-target test cannot see.

`get_credit_market_breadth` — what *kind* of stress is in the corporate tape?
Its one validated job is separating a duration selloff (IG making 52-week lows
while HY makes highs) from genuine credit stress (HY making lows), which a single
index spread cannot do. That part is descriptive and needs no calibration.

The 144A cut is reported as context only. The "144A cracks first" tripwire this
tool was originally built to watch **was measured and failed** — 0 of 7 firings
preceded a ≥50bp HY OAS widening against a 27% base rate, and the pattern turns
out to track new issuance rather than distress (a bond issued this year cannot
print a 52-week high, so a growing 144A universe depresses the count). See
scripts/analyze_credit_divergence.py.

Both tools gate nothing. Their provenance limits — T+1 evaluated marks, nominal
spreads, aggregate-not-single-name — are printed with every result rather than
buried here.
"""

import asyncio
from collections import defaultdict
from datetime import date, timedelta
from sqlite3 import Connection

from fastmcp import Context, FastMCP
from trading_clients.bond_math import (
    TREASURY_CMT_TENORS,
    BondValuation,
    value_bond,
)
from trading_clients.endpoint import Endpoint
from trading_clients.endpoints import finra, fred, openfigi, ssga
from trading_clients.endpoints.finra import (
    GRADE_ALL,
    GRADE_CONV,
    GRADE_HY,
    GRADE_IG,
    MarketBreadthResponse,
    MarketSentimentResponse,
)
from trading_clients.endpoints.ssga import CORPORATE_BOND_FUNDS, SsgaHolding
from trading_clients.finra_client import FinraClient
from trading_clients.table_helpers import md_table

from trading_mcp.db import credit_breadth
from trading_mcp.helpers import _db, _finra, _fred, _openfigi, _result_or_warn, _ssga

mcp = FastMCP("credit-tools")

# ICE BofA cohort spreads on FRED. Option-adjusted, so not like-for-like with the
# nominal G-spreads computed here — close enough to rank an issuer against its
# cohort, not close enough to quote a basis.
# SERIES-ID TRAP: BAMLH0A2HYB is single-B; BAMLH0A3HYC is CCC-*and-lower*.
COHORT_OAS: tuple[tuple[str, str], ...] = (
    ("BAMLC0A0CM", "IG corporate OAS"),
    ("BAMLH0A0HYM2", "HY broad OAS"),
    ("BAMLH0A2HYB", "Single-B OAS"),
    ("BAMLH0A3HYC", "CCC & lower OAS"),
)

# Marks for one bond can differ slightly between funds (different pricing
# vendors / strike times). Beyond this, say so rather than silently picking one.
_MARK_DISAGREEMENT_PTS = 0.50

# Recent weekdays checked against the stored history on every call. Small: the
# backfill script owns deep history, this only closes the gap since last use
# (and absorbs a holiday or two).
_CATCHUP_WEEKDAYS = 6

# The trend now reads from SQLite rather than one request per session, so a
# long window costs a single query — no reason to cap it as tightly as the
# live-fetch version did.
_MAX_TREND_SESSIONS = 250

# Rows printed in the trend table. The tally above summarizes the rest of the
# window, so a 250-session request doesn't dump 250 rows into the context.
_TREND_ROW_LIMIT = 15

# Below this the "fired X of N sessions" rate is too small a sample to mean
# anything, so the tally is suppressed rather than shown as a misleading percent.
_TALLY_MIN_SESSIONS = 20

# Past this many bonds, print the tenor-bucketed curve instead of every line —
# a large IG issuer runs to 50+ bonds and the shape is the point, not the rows.
_DETAIL_ROW_LIMIT = 20

_TENOR_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-2y", 0.0, 2.0),
    ("2-5y", 2.0, 5.0),
    ("5-10y", 5.0, 10.0),
    ("10-20y", 10.0, 20.0),
    ("20y+", 20.0, 1e9),
)


def _fred_latest(resp: fred.ObservationsResponse | None) -> tuple[date | None, float | None]:
    """Most recent non-missing observation. FRED marks gaps with '.'."""
    if resp is None:
        return None, None
    for obs in resp.observations:
        raw = obs.get("value")
        if raw in (None, "", "."):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        try:
            d = date.fromisoformat(str(obs.get("date", "")))
        except ValueError:
            d = None
        return d, value
    return None, None


def _recent_weekdays(count: int, end: date) -> list[date]:
    """`count` weekdays ending at or before `end`, most recent first.

    Weekends are skipped up front because FINRA answers them with an empty 204 —
    a wasted round trip on a per-date-partitioned API.
    """
    out: list[date] = []
    cursor = end
    while len(out) < count:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor -= timedelta(days=1)
    return out


# ═══════════════════════════════════════════════════════════════
# Tool 1 — single-name issuer credit
# ═══════════════════════════════════════════════════════════════


def _pick_marks(
    matches: list[tuple[str, SsgaHolding]],
) -> tuple[dict[str, tuple[str, SsgaHolding]], list[str]]:
    """Collapse per-fund holdings to one row per ISIN, flagging mark disagreement.

    The same bond sits in several funds in the panel. We keep the largest
    position (the most consequential mark) and warn when the funds' implied
    prices disagree by more than half a point, which is a signal the evaluated
    price is soft.
    """
    by_isin: dict[str, list[tuple[str, SsgaHolding]]] = defaultdict(list)
    for fund, holding in matches:
        by_isin[holding.identifier].append((fund, holding))

    chosen: dict[str, tuple[str, SsgaHolding]] = {}
    notes: list[str] = []
    for isin, rows in by_isin.items():
        rows.sort(key=lambda r: r[1].par_value or 0, reverse=True)
        chosen[isin] = rows[0]
        if len(rows) > 1:
            prices = [
                (h.market_value / h.par_value * 100.0)
                for _, h in rows
                if h.par_value and h.market_value
            ]
            if prices and (max(prices) - min(prices)) > _MARK_DISAGREEMENT_PTS:
                funds = ", ".join(f for f, _ in rows)
                notes.append(
                    f"{isin}: funds disagree on the mark by "
                    f"{max(prices) - min(prices):.2f}pts ({funds})"
                )
    return chosen, notes


def _bucket_table(valued: list[tuple[str, BondValuation]]) -> str:
    """Summarize a large issuer curve by tenor bucket.

    Median rather than mean: one off-the-run bond with a stale mark shouldn't
    move the bucket. The min-max column is what shows whether the curve is
    orderly or has a dislocated point worth pulling detail on.
    """
    rows = []
    for label, lo_y, hi_y in _TENOR_BUCKETS:
        members = [v for _, v in valued if lo_y <= v.years_to_maturity < hi_y]
        spreads = sorted(v.g_spread_bp for v in members if v.g_spread_bp is not None)
        if not spreads:
            continue
        ytms = sorted(v.ytm_pct for v in members if v.ytm_pct is not None)
        rows.append(
            [
                label,
                str(len(members)),
                f"{ytms[len(ytms) // 2]:.2f}%" if ytms else "—",
                f"{spreads[len(spreads) // 2]:,.0f}bp",
                f"{spreads[0]:,.0f}–{spreads[-1]:,.0f}bp",
            ]
        )
    return md_table(["Tenor", "Bonds", "Median YTM", "Median G-spread", "Range"], rows)


def _distinct_bonds(
    listings: list[openfigi.OpenFigiBond],
) -> dict[tuple[float, date], list[openfigi.OpenFigiBond]]:
    """Group tranche listings into the actual bonds they represent.

    A single issue shows up several times in OpenFIGI — a 144A tranche, a Reg S
    tranche, sometimes a registered exchange version — all sharing one coupon and
    maturity. Counting listings would badly overstate how many bonds an issuer
    has, and therefore understate coverage.
    """
    grouped: dict[tuple[float, date], list[openfigi.OpenFigiBond]] = defaultdict(list)
    for b in listings:
        grouped[(round(b.coupon_pct, 4), b.maturity)].append(b)
    return dict(grouped)


def _missing_reason(
    coupon: float, listings: list[openfigi.OpenFigiBond], median_priced_coupon: float
) -> str:
    """Best available explanation for why a bond carries no mark.

    The convertible test is a heuristic, not a field: OpenFIGI doesn't flag
    converts, but a coupon far below the issuer's straight debt is the giveaway
    — a borrower paying 9.75% cash does not also issue at 1.75% without handing
    over equity conversion. Worth calling out because a convertible's price is
    driven by the stock, so reading it as a credit spread is a category error.
    """
    if median_priced_coupon and coupon < median_priced_coupon / 2:
        return "likely a convertible — price is equity-driven, not a credit read"
    # Only claim an offshore listing when a real venue is named and isn't TRACE.
    # A blank code means unknown and "NOT LISTED" means exactly that — neither
    # implies a foreign tranche.
    venues = {(b.exch_code or "").strip().upper() for b in listings}
    named = {v for v in venues if v and v != "NOT LISTED"}
    if named and "TRACE" not in named:
        return f"listed {'/'.join(sorted(named))}, not TRACE — offshore or non-USD tranche"
    if venues == {"NOT LISTED"}:
        return "no secondary listing — unlisted tranche"
    return "not held by any fund in the SPDR panel"


@mcp.tool()
async def get_issuer_credit(
    ctx: Context, ticker: str, issuer_name: str = "", detail: bool = False
) -> str:
    """Get an issuer's outstanding bond prices, yields, and spreads to Treasuries.

    Answers "what does this company's own debt cost in the secondary market, and
    is that consistent with what its equity is doing?" Use it when a thesis turns
    on financing — a debt-funded buildout, a refinancing wall, a covenant test —
    because credit usually reprices such a name before equity does.

    Returns per bond: implied clean price, yield to maturity, the interpolated
    Treasury at that maturity, and the nominal G-spread; then the issuer's spread
    range against ICE BofA cohort spreads (IG / HY / single-B / CCC) so the level
    can be read as "trades like a B" or "trades like a CCC"; then a coverage
    report naming bonds that exist but could not be priced.

    Args:
        ticker: Issuer's equity ticker (e.g. "CRWV", "ORCL"). Used to find the
            bond universe — bond tickers carry the equity ticker as their first
            token.
        issuer_name: Optional override for the name used to match holdings rows
            (e.g. "COREWEAVE INC"). Supply this when the bond issuer's legal name
            differs from the equity's, or when the ticker lookup finds nothing.
        detail: Force the per-bond table. Issuers with more than 20 bonds default
            to a tenor-bucketed spread curve, since for a large investment-grade
            borrower the shape of the curve is the read, not the individual lines.

    Provenance, which matters for how much weight to put on the numbers:
      - Prices are **T+1 pricing-service marks from ETF holdings files, not
        trade prints.** For a thinly-traded high-yield bond the evaluated price
        may be a matrix estimate. Good for tracking a trend, not a hittable quote.
      - Yields are **YTM, not YTW.** Most HY bonds are callable and holdings
        files carry no call schedule; for a bond below par, YTM reads slightly
        above YTW.
      - Spreads are **nominal G-spreads, not OAS.** FRED's cohort spreads *are*
        option-adjusted, so an issuer's nominal spread reads a little wide
        against them. Compare magnitudes and direction, not basis points.
      - Coverage is whatever the SPDR corporate panel holds. Euro tranches and
        off-index private placements will be missing; the coverage line says so.
    """
    tkr = ticker.strip().upper()
    openfigi_client = _openfigi(ctx)
    ssga_client = _ssga(ctx)
    fred_client = _fred(ctx)

    warnings: list[str] = []

    # ── Universe (OpenFIGI) + marks (SSGA panel) + curve (FRED), concurrently ──
    fund_tickers = [f for f, _ in CORPORATE_BOND_FUNDS]
    curve_series = [s for s, _ in TREASURY_CMT_TENORS]

    tasks = [
        openfigi_client.post(openfigi.SEARCH, openfigi.BondSearchRequest(query=tkr)),
        *[ssga_client.get(ssga.HOLDINGS, ssga.HoldingsRequest(ticker=f)) for f in fund_tickers],
        *[
            fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(s, 5))
            for s in curve_series
        ],
        *[
            fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(s, 5))
            for s, _ in COHORT_OAS
        ],
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    idx = 0
    universe = _result_or_warn(
        results, idx, "OpenFIGI search", warnings, openfigi.BondSearchResponse
    )
    idx += 1

    holdings: list[tuple[str, ssga.SsgaHoldingsResponse]] = []
    for fund in fund_tickers:
        resp = _result_or_warn(results, idx, f"SSGA {fund}", warnings, ssga.SsgaHoldingsResponse)
        idx += 1
        if resp is not None:
            holdings.append((fund, resp))

    curve: list[tuple[float, float]] = []
    for series, tenor in TREASURY_CMT_TENORS:
        resp = _result_or_warn(results, idx, f"FRED {series}", warnings, fred.ObservationsResponse)
        idx += 1
        _, value = _fred_latest(resp)
        if value is not None:
            curve.append((tenor, value))

    cohort: list[tuple[str, date | None, float | None]] = []
    for series, label in COHORT_OAS:
        resp = _result_or_warn(results, idx, f"FRED {series}", warnings, fred.ObservationsResponse)
        idx += 1
        obs_date, value = _fred_latest(resp)
        cohort.append((label, obs_date, value))

    # The publisher's own as-of date drives both the yield math and the
    # matured-bond filter, so it has to be settled before anything else.
    as_of_dates = {resp.as_of for _, resp in holdings if resp.as_of}
    asof = max(as_of_dates) if as_of_dates else date.today()

    # ── Resolve the names used to match holdings rows ──
    # Scoped to the ticker prefix: a bare search for "IREN" also returns the
    # unrelated Italian utility IREN SpA, which has more bonds and would
    # otherwise win the name vote outright.
    needles: list[str] = []
    if issuer_name.strip():
        needles.append(issuer_name.strip())
    elif universe is not None:
        needles.extend(universe.issuer_names(tkr))

    if not needles:
        why = "; ".join(warnings) if warnings else "no bonds found for that ticker"
        return (
            f"## Issuer credit — {tkr}\n\n"
            f"Could not determine an issuer name to match holdings against ({why}).\n\n"
            "Retry with `issuer_name` set to the bond issuer's legal name as it "
            'appears in a holdings file (e.g. "COREWEAVE INC").'
        )

    matches: list[tuple[str, SsgaHolding]] = []
    for fund, resp in holdings:
        for h in resp.matching(needles):
            matches.append((fund, h))

    chosen, mark_notes = _pick_marks(matches)

    # ── Value every matched bond ──
    valued: list[tuple[str, BondValuation]] = []
    for fund, holding in chosen.values():
        if holding.coupon_pct is None or holding.maturity is None:
            continue
        v = value_bond(
            isin=holding.identifier,
            name=holding.name,
            coupon_pct=holding.coupon_pct,
            maturity=holding.maturity,
            market_value=holding.market_value or 0.0,
            par_value=holding.par_value or 0.0,
            asof=asof,
            curve=curve,
        )
        if v is not None:
            valued.append((fund, v))
    valued.sort(key=lambda t: t[1].maturity)

    # ── Render ──
    matched_name = needles[0]
    out: list[str] = [f"## Issuer credit — {tkr} ({matched_name})", ""]

    if not valued:
        out.append(
            "No priced bonds found. The SPDR corporate panel "
            f"({', '.join(fund_tickers)}) holds nothing matching "
            f"`{matched_name}`."
        )
        live = universe.live(asof, tkr) if universe is not None else []
        if live:
            out.extend(
                [
                    "",
                    f"OpenFIGI does list {len(live)} live bond(s) for this issuer, so "
                    "this is a coverage gap (off-index, convertible, or non-USD paper), "
                    "not an absence of debt:",
                    "",
                    md_table(
                        ["Ticker", "Issuer", "Coupon", "Maturity", "Type"],
                        [
                            [
                                b.ticker,
                                b.issuer_name,
                                f"{b.coupon_pct:g}%",
                                b.maturity.isoformat(),
                                "144A" if b.is_144a else (b.security_type or ""),
                            ]
                            for b in live
                        ],
                    ),
                ]
            )
        if warnings:
            out.extend(["", "**Warnings:** " + "; ".join(warnings)])
        return "\n".join(out)

    out.append(f"Marks as of **{asof.isoformat()}** (SSGA holdings, T+1 evaluated prices).")
    out.append("")

    # A big IG issuer has dozens of bonds and the analytical object is the shape
    # of its spread curve, not each line. Bucket by tenor past the threshold and
    # let the caller ask for detail.
    show_detail = detail or len(valued) <= _DETAIL_ROW_LIMIT
    if not show_detail:
        out.extend(
            [
                f"### Spread curve — {len(valued)} bonds by tenor",
                "",
                _bucket_table(valued),
                "",
                f"_Bucketed because this issuer has more than {_DETAIL_ROW_LIMIT} bonds. "
                "Pass `detail=True` for every line._",
                "",
            ]
        )
    else:
        out.append(
            md_table(
                ["Bond", "ISIN", "Price", "YTM", "Tsy", "G-spread", "Yrs", "Fund"],
                [
                    [
                        f"{v.coupon_pct:g}% {v.maturity.strftime('%b-%Y')}",
                        v.isin,
                        f"{v.clean_price:.2f}",
                        f"{v.ytm_pct:.2f}%" if v.ytm_pct is not None else "—",
                        f"{v.benchmark_pct:.2f}%" if v.benchmark_pct is not None else "—",
                        f"{v.g_spread_bp:,.0f}bp" if v.g_spread_bp is not None else "—",
                        f"{v.years_to_maturity:.1f}",
                        fund,
                    ]
                    for fund, v in valued
                ],
            )
        )
        out.append("")

    # ── Cohort context ──
    spreads = [v.g_spread_bp for _, v in valued if v.g_spread_bp is not None]
    if spreads:
        lo, hi = min(spreads), max(spreads)
        mid = sorted(spreads)[len(spreads) // 2]
        out.append(
            f"**Issuer G-spread range:** {lo:,.0f}–{hi:,.0f}bp (median {mid:,.0f}bp) "
            f"across {len(spreads)} bond(s)."
        )
        out.append("")

        rows = []
        for label, obs_date, value in cohort:
            if value is None:
                rows.append([label, "—", "—", ""])
                continue
            bp = value * 100.0
            ratio = mid / bp if bp else None
            rows.append(
                [
                    label,
                    f"{bp:,.0f}bp",
                    f"{ratio:.2f}x" if ratio else "—",
                    obs_date.isoformat() if obs_date else "",
                ]
            )
        out.append(md_table(["Cohort benchmark", "OAS", "Issuer median ÷ cohort", "As of"], rows))
        out.append("")
        out.append(
            "_Cohort spreads are option-adjusted; the issuer figures are nominal "
            "G-spreads on callable paper, so the ratio runs slightly high. Read it "
            "as a rating-cohort placement, not a precise basis._"
        )
        out.append("")

    # ── Coverage ──
    if universe is not None:
        # Reference data keeps bonds long after they mature (ORCL still lists
        # 2001 paper). A matured bond is not a coverage gap.
        listings = universe.live(asof, tkr)
        distinct = _distinct_bonds(listings)
        priced_keys = {(round(v.coupon_pct, 4), v.maturity) for _, v in valued}
        missing = [(k, bs) for k, bs in distinct.items() if k not in priced_keys]

        if len(valued) > len(distinct):
            # The search returns one page, so for a large issuer the holdings
            # panel legitimately finds more bonds than the universe lists.
            # Printing "priced 52 of 34" would be nonsense.
            out.append(
                f"**Coverage:** priced {len(valued)} bond(s). The OpenFIGI universe "
                f"came back with only {len(distinct)} live issue(s) — fewer than we "
                "priced — so it is paginated/incomplete here and the gap list below "
                "is not exhaustive."
            )
        else:
            out.append(
                f"**Coverage:** priced {len(valued)} of {len(distinct)} distinct live "
                f"bond(s) ({len(listings)} tranche listings — most bonds appear twice, "
                "as a 144A and a Reg S tranche of the same issue)."
            )
        if missing:
            median_coupon = sorted(v.coupon_pct for _, v in valued)[len(valued) // 2]
            out.append("")
            out.append(
                md_table(
                    ["Unpriced bond", "Maturity", "Tranches", "Why it's missing"],
                    [
                        [
                            f"{coupon:g}%",
                            maturity.isoformat(),
                            ", ".join(sorted({b.qualifier or b.security_type or "?" for b in bs})),
                            _missing_reason(coupon, bs, median_coupon),
                        ]
                        for (coupon, maturity), bs in sorted(missing, key=lambda t: t[0][1])
                    ],
                )
            )
            out.append("")
            out.append(
                "_Unpriced = held by no fund in the SPDR panel. Euro tranches, offshore "
                "listings, and convertibles are all routinely absent; not a data error._"
            )
        out.append("")

    if mark_notes:
        out.append("**Mark disagreement across funds:** " + "; ".join(mark_notes))
        out.append("")
    if warnings:
        out.append("**Warnings:** " + "; ".join(warnings))
        out.append("")

    out.append(
        "_Sources: SSGA daily holdings (prices, T+1 evaluated marks — not trade "
        "prints) · OpenFIGI (bond universe) · FRED (Treasury CMT curve, ICE BofA "
        "cohort OAS). Yields are YTM, not YTW._"
    )
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# Tool 2 — market-wide credit breadth and flow
# ═══════════════════════════════════════════════════════════════


def _response_from_rows(rows: list[dict]) -> MarketBreadthResponse:
    """Rebuild the response model from stored rows so rendering is identical
    whether a session came from the API or the local history."""
    return MarketBreadthResponse(
        rows=[
            finra.BreadthRow(
                trade_date=date.fromisoformat(r["trade_date"]),
                grade=r["grade"],
                total_trades=r["total_trades"],
                advances=r["advances"],
                declines=r["declines"],
                unchanged=r["unchanged"],
                fifty_two_week_high=r["fifty_two_week_high"],
                fifty_two_week_low=r["fifty_two_week_low"],
                total_volume_mm=r["total_volume_mm"],
            )
            for r in rows
        ]
    )


async def _catch_up(client: FinraClient, conn: Connection, warnings: list[str]) -> None:
    """Fetch and store any recent weekday the history doesn't have yet.

    Bounded to a short window, so the steady-state cost of a tool call is one or
    two requests per universe — the backfill script owns deep history. A session
    that comes back empty is only recorded as permanently empty once it is old
    enough that a 204 can't just mean "not published yet".
    """
    recent = _recent_weekdays(_CATCHUP_WEEKDAYS, date.today())
    pending: list[tuple[date, str, Endpoint]] = []
    for universe, endpoint in (
        (credit_breadth.UNIVERSE_ALL, finra.MARKET_BREADTH),
        (credit_breadth.UNIVERSE_144A, finra.MARKET_BREADTH_144A),
    ):
        known = await credit_breadth.known_dates(conn, universe)
        pending.extend((d, universe, endpoint) for d in recent if d.isoformat() not in known)
    if not pending:
        return

    results = await asyncio.gather(
        *[client.post(ep, finra.TradeDateRequest(trade_date=d)) for d, _, ep in pending],
        return_exceptions=True,
    )
    today = date.today()
    for i, (day, universe, _) in enumerate(pending):
        resp = _result_or_warn(
            results, i, f"FINRA {universe} {day}", warnings, MarketBreadthResponse
        )
        if resp is None:
            continue
        if not resp.rows:
            if (today - day).days >= credit_breadth.EMPTY_IS_FINAL_AFTER_DAYS:
                await credit_breadth.mark_empty(conn, day, universe)
            continue
        await credit_breadth.upsert_session(
            conn,
            day,
            universe,
            [
                {
                    "grade": r.grade,
                    "total_trades": r.total_trades,
                    "advances": r.advances,
                    "declines": r.declines,
                    "unchanged": r.unchanged,
                    "fifty_two_week_high": r.fifty_two_week_high,
                    "fifty_two_week_low": r.fifty_two_week_low,
                    "total_volume_mm": r.total_volume_mm,
                }
                for r in resp.rows
            ],
        )


async def _stored_sessions(
    conn: Connection, universe: str, sessions: int
) -> dict[date, MarketBreadthResponse]:
    """The last `sessions` stored sessions for one universe, keyed by date."""
    grouped: dict[date, list[dict]] = defaultdict(list)
    for grade in finra.GRADE_ORDER:
        for r in await credit_breadth.select_grade_series(conn, universe, grade, sessions):
            grouped[date.fromisoformat(r["trade_date"])].append(r)
    # Each grade query returns its own newest-N, so a grade missing on some day
    # can drag an older date in; keep only the newest N dates overall.
    newest = sorted(grouped, reverse=True)[:sessions]
    return {d: _response_from_rows(grouped[d]) for d in newest}


def _breadth_read(all_corp: MarketBreadthResponse, corp_144a: MarketBreadthResponse) -> list[str]:
    """Interpret the IG-vs-HY and broad-vs-144A splits.

    The distinction worth having: a broad index spread cannot tell a *duration*
    selloff (long IG paper marked down by rising Treasury yields, spreads fine)
    from a *credit* selloff (HY marked down on default risk). The 52-week
    high/low counts separate them, because IG is where the duration lives and HY
    is where the credit risk lives.
    """
    lines: list[str] = []
    ig = all_corp.by_grade(GRADE_IG)
    hy = all_corp.by_grade(GRADE_HY)
    hy_144a = corp_144a.by_grade(GRADE_HY)

    if ig is not None and hy is not None:
        ig_net, hy_net = ig.net_new_highs, hy.net_new_highs
        if ig_net < 0 <= hy_net:
            lines.append(
                f"**Duration, not credit.** Investment grade is making more 52-week "
                f"lows than highs ({ig.fifty_two_week_low:,} vs "
                f"{ig.fifty_two_week_high:,}) while high yield is the mirror "
                f"({hy.fifty_two_week_high:,} highs vs {hy.fifty_two_week_low:,} lows). "
                "Long IG paper is being repriced by the Treasury curve, not by default "
                "risk — a broad HY OAS reading cannot make this distinction."
            )
        elif hy_net < 0 <= ig_net:
            lines.append(
                f"**Credit, not duration.** High yield is making more 52-week lows than "
                f"highs ({hy.fifty_two_week_low:,} vs {hy.fifty_two_week_high:,}) while "
                "investment grade holds up. This is the ordering that matters for a "
                "financing-dependent thesis — spread risk, not rate risk."
            )
        elif ig_net < 0 and hy_net < 0:
            lines.append(
                f"**Broad-based weakness.** Both grades are making net new 52-week lows "
                f"(IG {ig_net:+,}, HY {hy_net:+,}). Rates and spreads are moving together."
            )
        else:
            lines.append(
                f"**Benign.** Both grades net-positive on 52-week highs "
                f"(IG {ig_net:+,}, HY {hy_net:+,})."
            )

    if hy_144a is not None and hy is not None:
        hy_144a_net = hy_144a.net_new_highs
        state = "below" if hy_144a_net < 0 <= hy.net_new_highs else "in line with"
        lines.append(
            f"144A high yield net new highs {hy_144a_net:+,} vs {hy.net_new_highs:+,} "
            f"broad — {state} the broad market. **Not a warning either way.** "
            "Measured over 765 sessions (2023-07 →), this divergence fired on 13.6% "
            "of sessions and preceded a ≥50bp HY OAS widening **0 of 7 times** at its "
            "best threshold, against a 27% base rate. It is largely an artifact: the "
            "144A universe grew 23% since 2023 and newly issued bonds cannot print a "
            "52-week high, so heavy 144A issuance mechanically depresses this number "
            "— it reads *lowest* when the speculative channel is busiest. Re-check "
            "with scripts/analyze_credit_divergence.py once a real credit cycle is "
            "in the sample."
        )
    return lines


@mcp.tool()
async def get_credit_market_breadth(ctx: Context, sessions: int = 10) -> str:
    """Get daily corporate bond market breadth and dealer/customer flow from FINRA.

    Answers "is the corporate funding market opening or closing?" using the whole
    reported tape rather than a single index spread. Two things it can do that a
    broad HY OAS number cannot:

      - **Separate duration stress from credit stress.** 52-week high/low counts
        split by grade show whether long investment-grade paper is being marked
        down by the Treasury curve or whether high yield is being marked down on
        default risk.
      - **Show the 144A market separately.** 144A is the private-placement
        channel speculative and unrated issuers fund through. Reported as
        context, **not as a tripwire**: the "144A cracks first" divergence was
        measured over 765 sessions and failed (0 of 7 firings preceded a ≥50bp
        HY OAS widening, against a 27% base rate), largely because a growing
        144A universe mechanically suppresses 52-week-high counts. Read the
        levels; don't act on the divergence.

    Also reports flow: customer buy vs customer sell vs inter-dealer volume, which
    says who is absorbing the paper when prices move.

    It also reports its own base rate — how often the 144A divergence fired in
    the requested window, and the current streak — so a single day's firing is
    always read against how often the pattern occurs anyway.

    Known scope limit, measured on the April-2025 episode: credit **lagged**
    equity there (HY OAS's first decisive widening came two days *after* the SPY
    peak; IG OAS troughed the same day). Spreads lead at credit-cycle tops, not
    at policy shocks, where everything reprices at once. What credit did get
    right was severity — HY +202bp vs IG +41bp marked it a risk-appetite shock
    rather than a solvency event, and the recovery was V-shaped.

    Args:
        sessions: Sessions of history for the window (1-250, default 10). Served
            from a local SQLite history, so a long window costs one query rather
            than one request per session; the trend table prints the most recent
            15 and the tally covers the rest. Run
            `scripts/backfill_credit_breadth.py` to populate history back to
            mid-2023 — without it only sessions this tool has already seen are
            available.

    Caveats: aggregate market data only — there are no single-name prices here
    (use `get_issuer_credit` for those). Data is T+1. Volumes are $ millions.
    Requires a free FINRA developer credential with the Fixed Income Data user
    agreement accepted.
    """
    sessions = max(1, min(_MAX_TREND_SESSIONS, sessions))
    client = _finra(ctx)
    conn = _db(ctx)
    warnings: list[str] = []

    # Catch the local history up to today, then read the trend out of it. The
    # trade date is a partition key, so pulling N sessions live is N round trips
    # every call; against the stored series it's one query and the window can be
    # long. Every invocation also extends the series, which is what lets the
    # shadow period actually accumulate evidence.
    await _catch_up(client, conn, warnings)

    broad = await _stored_sessions(conn, credit_breadth.UNIVERSE_ALL, sessions)
    a144 = await _stored_sessions(conn, credit_breadth.UNIVERSE_144A, sessions)

    if not broad:
        detail = "; ".join(warnings[:3]) if warnings else "no sessions returned data"
        return (
            "## Corporate credit market breadth\n\n"
            f"No stored or live sessions available ({detail}).\n\n"
            "If this is a 404, the FINRA token predates accepting the Fixed Income "
            "Data user agreement — restart the server to mint a fresh one. If the "
            "history is simply empty, run "
            "`packages/trading-mcp/scripts/backfill_credit_breadth.py`."
        )

    latest = max(broad)
    sess_dates = sorted(broad, reverse=True)[:sessions]

    # Flow only for the latest session — the trend lives in the breadth table.
    flow_results = await asyncio.gather(
        client.post(finra.MARKET_SENTIMENT, finra.TradeDateRequest(trade_date=latest)),
        client.post(finra.MARKET_SENTIMENT_144A, finra.TradeDateRequest(trade_date=latest)),
        return_exceptions=True,
    )
    flow_broad = _result_or_warn(
        flow_results, 0, "FINRA sentiment", warnings, MarketSentimentResponse
    )
    flow_144a = _result_or_warn(
        flow_results, 1, "FINRA 144A sentiment", warnings, MarketSentimentResponse
    )

    out: list[str] = [
        f"## Corporate credit market breadth — {latest.isoformat()}",
        "",
        "### All corporates",
        "",
        broad[latest].to_output(),
        "",
    ]

    if latest in a144:
        out.extend(["### 144A only (private placements)", "", a144[latest].to_output(), ""])

    read = _breadth_read(broad[latest], a144.get(latest, MarketBreadthResponse()))
    if read:
        out.extend(["### Read", ""])
        out.extend(f"- {line}" for line in read)
        out.append("")

    if flow_broad is not None and flow_broad.rows:
        out.extend(["### Flow — all corporates ($MM)", "", flow_broad.to_output(), ""])
    if flow_144a is not None and flow_144a.rows:
        out.extend(["### Flow — 144A ($MM)", "", flow_144a.to_output(), ""])
    if flow_broad is not None and flow_broad.rows:
        out.append(
            "_Net customer = customer buy minus customer sell. Positive means "
            "customers are lifting bonds from dealers (dealer inventory falling)._"
        )
        out.append("")

    # ── Divergence tally over the whole requested window ──
    # The tool's own base rate. Whether a firing today means anything depends on
    # how often it happens when nothing is wrong, so the count travels with the
    # reading rather than living in a script nobody re-runs.
    # Only sessions carrying BOTH universes can be evaluated. Scoring the rest
    # as "did not fire" would quietly deflate the rate whenever 144A history is
    # thinner than broad — which is exactly the state a partial backfill leaves.
    def _diverged(d: date) -> bool | None:
        b = broad[d].by_grade(GRADE_HY)
        a = a144[d].by_grade(GRADE_HY) if d in a144 else None
        if b is None or a is None:
            return None
        return a.net_new_highs < 0 <= b.net_new_highs

    verdicts = [(d, _diverged(d)) for d in sess_dates]
    scorable = [(d, v) for d, v in verdicts if v is not None]
    if len(scorable) >= _TALLY_MIN_SESSIONS:
        fired = sum(1 for _, v in scorable if v)
        streak = 0
        for _, v in verdicts:  # newest-first; an unscorable day breaks the streak
            if v:
                streak += 1
            else:
                break
        gap = len(sess_dates) - len(scorable)
        note = f" ({gap} session(s) lacked 144A data and are excluded)" if gap else ""
        out.extend(
            [
                f"**144A divergence tally:** fired on {fired} of {len(scorable)} scorable "
                f"sessions in this window ({fired / len(scorable) * 100:.0f}%); "
                f"current consecutive streak **{streak}**.{note}",
                "",
            ]
        )

    # ── Trend ──
    if len(sess_dates) > 1:
        shown = sess_dates[:_TREND_ROW_LIMIT]
        rows = []
        for d in shown:
            b_hy = broad[d].by_grade(GRADE_HY)
            b_ig = broad[d].by_grade(GRADE_IG)
            a_hy = a144[d].by_grade(GRADE_HY) if d in a144 else None
            rows.append(
                [
                    d.isoformat(),
                    f"{b_ig.ad_ratio:.2f}" if b_ig and b_ig.ad_ratio is not None else "—",
                    f"{b_ig.net_new_highs:+,}" if b_ig else "—",
                    f"{b_hy.ad_ratio:.2f}" if b_hy and b_hy.ad_ratio is not None else "—",
                    f"{b_hy.net_new_highs:+,}" if b_hy else "—",
                    f"{a_hy.ad_ratio:.2f}" if a_hy and a_hy.ad_ratio is not None else "—",
                    f"{a_hy.net_new_highs:+,}" if a_hy else "—",
                ]
            )
        heading = f"### Trend — last {len(shown)} session(s)"
        if len(shown) < len(sess_dates):
            heading += f" of {len(sess_dates)} in the window"
        out.extend(
            [
                heading,
                "",
                md_table(
                    [
                        "Date",
                        "IG A/D",
                        "IG net hi",
                        "HY A/D",
                        "HY net hi",
                        "144A HY A/D",
                        "144A HY net hi",
                    ],
                    rows,
                ),
                "",
            ]
        )

    conv = broad[latest].by_grade(GRADE_CONV)
    allsec = broad[latest].by_grade(GRADE_ALL)
    if allsec is not None:
        summary = f"{allsec.total_trades:,} trades on ${allsec.total_volume_mm / 1000:,.1f}B"
        if conv is not None:
            summary += f" · convertibles {conv.total_trades:,} trades"
        out.extend([f"_Session size: {summary}._", ""])

    if warnings:
        out.append("**Warnings:** " + "; ".join(warnings[:5]))
        out.append("")

    out.append(
        "_Source: FINRA Query API (fixedIncomeMarket), T+1. Aggregate market data "
        "— no single-name prices; use `get_issuer_credit` for those. Volumes in "
        "$ millions._"
    )
    return "\n".join(out)


__all__ = ["mcp", "get_issuer_credit", "get_credit_market_breadth"]
