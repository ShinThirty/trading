"""Macro and market-wide context: economic series, sector performance, market regime."""

import asyncio
from datetime import date, datetime, timedelta

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.endpoints import (
    bea,
    bls,
    cftc,
    fed,
    fmp,
    fred,
    polymarket,
    sentiment,
    squeeze_metrics,
)
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import kv_table, md_table

from trading_mcp.helpers import (
    _bea,
    _bls,
    _cftc,
    _exc_summary,
    _factset,
    _fed,
    _fmp,
    _fred,
    _naaim,
    _polymarket,
    _sentiment,
    _squeeze_metrics,
    _tradier,
    _year_ago,
)

mcp = FastMCP("macro-tools")

HISTORY_SYMBOLS = ["SPY", "SMH", "IWM", "RSP", *regime.SECTOR_ETFS]


@mcp.tool()
async def get_economic_data(
    ctx: Context, series_id: str, limit: int = 12, sort_order: str = "desc"
) -> str:
    """Get historical values for a FRED economic data series.

    series_id: FRED series ID. Common: 'CPIAUCSL' (CPI), 'GDP', 'UNRATE',
      'FEDFUNDS', 'T10Y2Y' (yield curve), 'VIXCLS' (VIX), 'PAYEMS' (payrolls),
      'UMCSENT' (sentiment), 'DGS10' (10Y yield).
    limit: number of most recent observations (default 12).
    sort_order: 'desc' (newest first) or 'asc'.

    Requires [fred] section in ~/.tradingrc.
    """
    req = fred.GetObservationsRequest(series_id, limit, sort_order)
    return (await _fred(ctx).get(fred.OBSERVATIONS, req)).to_output()


@mcp.tool()
async def get_fred_series_info(ctx: Context, series_id: str) -> str:
    """Get metadata for a FRED series: title, frequency, units, seasonal adjustment.

    series_id: FRED series ID (e.g. 'CPIAUCSL', 'GDP', 'VIXCLS').
    Requires [fred] section in ~/.tradingrc.
    """
    return (await _fred(ctx).get(fred.SERIES_INFO, fred.SeriesIdRequest(series_id))).to_output()


@mcp.tool()
async def search_fred_series(ctx: Context, query: str, limit: int = 10) -> str:
    """Search for FRED economic data series by keyword.

    query: search terms (e.g. 'inflation', 'housing starts', 'consumer credit').
    limit: max results to return (default 10).

    Use the returned series_id with get_economic_data to fetch actual values.
    Requires [fred] section in ~/.tradingrc.
    """
    return (await _fred(ctx).get(fred.SEARCH, fred.SearchRequest(query, limit))).to_output()


@mcp.tool()
async def get_sector_performance(ctx: Context, date: str, exchange: str = "NYSE") -> str:
    """Get sector performance for a specific date: average percentage change for each
    of 11 sectors (Technology, Healthcare, Financial Services, etc.), sorted best to worst.

    Useful for understanding sector rotation and whether a stock's movement is
    stock-specific or sector-wide.

    date: trading date (YYYY-MM-DD). Use a recent trading day (not weekend/holiday).
    exchange: 'NYSE' (default) or 'NASDAQ'.

    Requires [fmp] section in ~/.tradingrc.
    """
    return (
        await _fmp(ctx).get(fmp.SECTOR_PERFORMANCE, fmp.SectorPerformanceRequest(date, exchange))
    ).to_output()


@mcp.tool()
async def get_equity_risk_premium(ctx: Context) -> str:
    """Get the current S&P 500 equity risk premium with valuation-regime tier.

    ERP = forward earnings yield − 10Y Treasury yield. Determines how much
    equities compensate over risk-free, and therefore the rate at which
    earnings translate into multiples. A compressed or negative ERP means
    returns come from earnings only — any rate or earnings shock compresses
    multiples mechanically.

    Combines:
      - FactSet Earnings Insight forward 12-month P/E (Friday weekly PDF)
      - FRED DGS10 (10Y Treasury constant-maturity yield)

    Returns ERP in bps, regime tier (Generous / Fair / Tight / Compressed /
    Compressed-Negative), and 5y / 10y / quarter-end forward P/E context
    so the reader can decompose how much compression is from multiples vs
    rate level (the implied-ERP-at-historical-P/E rows).

    Cache bottleneck is the weekly FactSet refresh; daily polling adds nothing.
    Best fit: biweekly review, plus any week with a major rate or earnings shock.

    Requires [fred] section in ~/.tradingrc. FactSet uses no auth.
    """
    fred_client = _fred(ctx)
    factset_client = _factset(ctx)

    results = await asyncio.gather(
        factset_client.get_earnings_insight(),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS10", 2)),
        return_exceptions=True,
    )

    warnings: list[str] = []
    fs_resp = results[0] if not isinstance(results[0], BaseException) else None
    if fs_resp is None:
        warnings.append(_exc_summary("FactSet Earnings Insight", results[0]))
    fred_resp = results[1] if not isinstance(results[1], BaseException) else None
    if fred_resp is None:
        warnings.append(_exc_summary("FRED DGS10", results[1]))

    out: list[str] = []
    out.extend(_warnings_section(warnings))

    if fs_resp is None or fred_resp is None:
        out.append("(insufficient data — both FactSet Earnings Insight and FRED DGS10 required)")
        return "\n".join(out)

    fwd_pe = fs_resp.forward_pe
    fwd_pe_5y = fs_resp.forward_pe_5y_avg
    fwd_pe_10y = fs_resp.forward_pe_10y_avg
    fwd_pe_qe = fs_resp.forward_pe_quarter_end
    publish_date = fs_resp.publish_date

    dgs10, dgs10_date = regime.parse_fred_value(fred_resp.observations)

    if fwd_pe is None:
        out.append("(FactSet forward 12M P/E not parsed from latest PDF — see narrative)")
        return "\n".join(out)
    if dgs10 is None:
        out.append("(FRED DGS10 value unavailable for latest observation)")
        return "\n".join(out)

    earnings_yield = 100.0 / fwd_pe  # percent
    erp_bps = (earnings_yield - dgs10) * 100
    label, _ = regime.classify_erp(erp_bps)

    out.append("## Equity Risk Premium (S&P 500)")
    out.append("")
    out.append(f"**Regime: {label}** — ERP {erp_bps:+.0f} bps")
    meta_parts: list[str] = []
    if publish_date:
        meta_parts.append(f"FactSet {publish_date}")
    if dgs10_date:
        meta_parts.append(f"DGS10 {dgs10_date}")
    if meta_parts:
        out.append(f"*{' • '.join(meta_parts)}*")

    # Warn if FactSet and DGS10 dates have decoupled — ERP loses meaning when
    # the rate side has moved meaningfully since the P/E snapshot was published.
    fs_d = _parse_factset_publish_date(publish_date) if publish_date else None
    fred_d = _safe_iso_date(dgs10_date) if dgs10_date else None
    if fs_d and fred_d:
        gap_days = abs((fs_d - fred_d).days)
        if gap_days > 7:
            out.append(
                f"⚠ FactSet ({publish_date}) and DGS10 ({dgs10_date}) differ by "
                f"{gap_days} days — ERP read may have decoupled from current rates. "
                "Re-pull when next FactSet PDF lands."
            )
    out.append("")

    headline = {
        "Forward 12M P/E": f"{fwd_pe:.2f}",
        "Forward earnings yield": f"{earnings_yield:.2f}%",
        "10Y Treasury (DGS10)": f"{dgs10:.2f}%",
        "ERP": f"{erp_bps:+.0f} bps",
    }
    out.append(kv_table(headline, key_header="Component"))

    # Decomposition: hold DGS10 fixed, swap P/E for historical anchors.
    # Tells the reader how much current compression is from multiples vs rates.
    context_rows: dict[str, str] = {}
    for label_, pe in (
        ("Fwd P/E 5y avg", fwd_pe_5y),
        ("Fwd P/E 10y avg", fwd_pe_10y),
        ("Fwd P/E quarter-end", fwd_pe_qe),
    ):
        if pe is None:
            continue
        delta_pct = (fwd_pe / pe - 1) * 100
        implied_erp_bps = (100.0 / pe - dgs10) * 100
        context_rows[label_] = (
            f"{pe:.1f} (current {delta_pct:+.0f}%) • "
            f"implied ERP at this P/E: {implied_erp_bps:+.0f} bps"
        )
    if context_rows:
        out.append("")
        out.append("**Context** (hold DGS10 fixed, swap P/E for historical anchor):")
        out.append(kv_table(context_rows, key_header="Anchor"))

    return "\n".join(out)


def _parse_factset_publish_date(s: str) -> date | None:
    """Parse FactSet 'Month D, YYYY' (e.g. 'May 15, 2026'). Returns None on failure."""
    try:
        return datetime.strptime(s, "%B %d, %Y").date()
    except (ValueError, TypeError):
        return None


def _safe_iso_date(s: str) -> date | None:
    """Parse 'YYYY-MM-DD'. Returns None on failure."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _obs_value_at(obs: list[dict], idx: int) -> float | None:
    """Read FRED obs[idx], walking forward past '.' (missing) values.

    Note: the lookback is approximate — if obs[idx] is missing (holiday), this
    returns obs[idx+1] etc., so a holiday-heavy window reads slightly farther
    back than requested. Acceptable drift for regime classification windows.
    """
    n = len(obs)
    for i in range(idx, n):
        v = obs[i].get("value", ".")
        if v == ".":
            continue
        try:
            return float(v)
        except (ValueError, TypeError):
            continue
    return None


@mcp.tool()
async def get_yield_curve_state(ctx: Context) -> str:
    """Get current Treasury yield curve state with regime classification.

    Fetches 2Y / 10Y / 30Y constant-maturity yields from FRED (DGS2 / DGS10 /
    DGS30), reports current levels and 4-week / 12-week changes, computes
    2s10s and 10s30s spreads, and classifies the curve regime:

    - **Bear Steepener**: yields rising, long end leading. Term-premium expansion
      or supply/inflation repricing (May 2026 pattern). Pressures equity multiples
      mechanically — discount rate up faster than earnings.
    - **Bear Flattener**: yields rising, short end leading. Fed-path repricing
      (hawkish hikes priced).
    - **Bull Steepener**: yields falling, short end leading. Fed cuts priced.
    - **Bull Flattener**: yields falling, long end leading. Duration bid /
      recession trade.
    - **Quiet**: |all moves| < 10 bps over 4w.
    - **Mixed**: tenor moves don't agree on direction.

    The leading-tenor diagnostic is the load-bearing piece: it tells you
    *what* is repricing (term premium vs Fed path vs duration bid) — not just
    that yields moved.

    Requires [fred] section in ~/.tradingrc.
    """
    fred_client = _fred(ctx)

    # 80 daily obs covers ~13 weeks of trading days with comfortable slack for
    # holiday clusters (Memorial Day, Thanksgiving) and any FRED publishing lag.
    series = [("DGS2", "2Y"), ("DGS10", "10Y"), ("DGS30", "30Y")]
    results = await asyncio.gather(
        *(
            fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, 80))
            for sid, _ in series
        ),
        return_exceptions=True,
    )

    warnings: list[str] = []
    obs_by_id: dict[str, list[dict]] = {}
    for (sid, _), r in zip(series, results, strict=True):
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(f"FRED {sid}", r))
        else:
            obs_by_id[sid] = r.observations or []

    out: list[str] = []
    out.extend(_warnings_section(warnings))

    # 4w ≈ 20 trading days, 12w ≈ 60 trading days. Newest-first.
    LOOKBACK_4W = 20
    LOOKBACK_12W = 60

    levels: dict[str, float | None] = {}
    changes_4w: dict[str, float | None] = {}
    changes_12w: dict[str, float | None] = {}
    latest_date = ""

    for sid, _ in series:
        obs = obs_by_id.get(sid, [])
        cur = _obs_value_at(obs, 0)
        prior_4w = _obs_value_at(obs, LOOKBACK_4W) if len(obs) > LOOKBACK_4W else None
        prior_12w = _obs_value_at(obs, LOOKBACK_12W) if len(obs) > LOOKBACK_12W else None
        levels[sid] = cur
        changes_4w[sid] = (
            (cur - prior_4w) * 100 if cur is not None and prior_4w is not None else None
        )
        changes_12w[sid] = (
            (cur - prior_12w) * 100 if cur is not None and prior_12w is not None else None
        )
        if obs and not latest_date:
            latest_date = obs[0].get("date", "")

    if all(v is None for v in levels.values()):
        out.append("(no FRED Treasury data available — DGS2/DGS10/DGS30 all empty)")
        return "\n".join(out)

    label, detail = regime.classify_curve_regime(
        changes_4w.get("DGS2"), changes_4w.get("DGS10"), changes_4w.get("DGS30")
    )

    out.append("## Yield Curve State")
    out.append("")
    out.append(f"**Regime: {label}** — {detail}")
    if latest_date:
        out.append(f"*as of {latest_date}*")
    out.append("")

    def _fmt_bps(b: float | None) -> str:
        return f"{b:+.0f} bps" if b is not None else "—"

    def _fmt_pct(p: float | None) -> str:
        return f"{p:.2f}%" if p is not None else "—"

    rows = [
        [tenor, _fmt_pct(levels[sid]), _fmt_bps(changes_4w[sid]), _fmt_bps(changes_12w[sid])]
        for sid, tenor in series
    ]
    out.append(md_table(["Tenor", "Yield", "4w Δ", "12w Δ"], rows))

    # Spreads
    spread_rows: list[list[str]] = []

    def _spread_row(name: str, long_sid: str, short_sid: str) -> None:
        long_lvl = levels[long_sid]
        short_lvl = levels[short_sid]
        if long_lvl is None or short_lvl is None:
            return
        cur_spread_bps = (long_lvl - short_lvl) * 100
        long_4w = changes_4w[long_sid]
        short_4w = changes_4w[short_sid]
        delta_4w = (
            f"{long_4w - short_4w:+.0f} bps"
            if long_4w is not None and short_4w is not None
            else "—"
        )
        spread_rows.append([name, f"{cur_spread_bps:+.0f} bps", delta_4w])

    _spread_row("2s10s", "DGS10", "DGS2")
    _spread_row("10s30s", "DGS30", "DGS10")
    if spread_rows:
        out.append("")
        out.append("**Spreads:**")
        out.append(md_table(["Spread", "Current", "4w Δ"], spread_rows))

    return "\n".join(out)


# Industry employment subseries from FRED. Display order matches BLS Table B-1
# convention (goods-producing → service-providing → government parents at end).
_INDUSTRY_SERIES: list[tuple[str, str]] = [
    ("USMINE", "Mining & logging"),
    ("USCONS", "Construction"),
    ("MANEMP", "Manufacturing"),
    ("USTRADE", "Trade, transport, utilities"),
    ("USINFO", "Information"),
    ("USFIRE", "Financial activities"),
    ("USPBS", "Professional & business services"),
    ("USEHS", "Education & health services"),
    ("USLAH", "Leisure & hospitality"),
    ("USGOVT", "Government"),
    ("USGOOD", "(Total goods-producing)"),
    ("SRVPRD", "(Total service-providing)"),
]


def _mom_change(obs: list[dict]) -> float | None:
    """obs is desc-sorted (newest first). Returns latest minus prior, or None."""
    if len(obs) < 2:
        return None
    try:
        return float(obs[0]["value"]) - float(obs[1]["value"])
    except (ValueError, KeyError):
        return None


def _mom_pct(obs: list[dict]) -> float | None:
    if len(obs) < 2:
        return None
    try:
        a, b = float(obs[0]["value"]), float(obs[1]["value"])
        return (a - b) / b * 100 if b else None
    except (ValueError, KeyError):
        return None


def _yoy_pct(obs: list[dict]) -> float | None:
    if len(obs) < 13:
        return None
    try:
        a, b = float(obs[0]["value"]), float(obs[12]["value"])
        return (a - b) / b * 100 if b else None
    except (ValueError, KeyError):
        return None


def _latest(obs: list[dict]) -> float | None:
    if not obs:
        return None
    try:
        return float(obs[0]["value"])
    except (ValueError, KeyError):
        return None


def _prior(obs: list[dict]) -> float | None:
    if len(obs) < 2:
        return None
    try:
        return float(obs[1]["value"])
    except (ValueError, KeyError):
        return None


def _warnings_section(warnings: list[str]) -> list[str]:
    """Return output lines for a warnings header, or [] if no warnings."""
    if not warnings:
        return []
    lines = ["⚠ Data source warnings (some fetches failed):"]
    for w in warnings:
        lines.append(f"  • {w}")
    lines.append("")
    return lines


def _collect_fred_obs(
    results: list,
    series_specs: list[tuple[str, int]],
    start_idx: int,
    warnings: list[str],
) -> dict[str, list[dict]]:
    """Pull observations out of a gather() result slice, appending failures
    to the shared warnings list. Returns successfully-fetched series only."""
    obs_by_id: dict[str, list[dict]] = {}
    for i, (sid, _) in enumerate(series_specs, start=start_idx):
        r = results[i]
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(f"FRED {sid}", r))
        else:
            obs_by_id[sid] = r.observations or []
    return obs_by_id


@mcp.tool()
async def get_jobs_report_texture(ctx: Context) -> str:
    """Latest BLS Employment Situation: headline + texture beneath the headline.

    Aggregates the BLS press release narrative (industry mix commentary,
    revisions wording, household survey detail) with FRED series for the
    underneath data (U-6, participation, hours, part-time, household-vs-
    establishment divergence, decimal-precision unemployment, industry mix
    by sector) and Tradier intraday quotes for the rate-sensitive tape
    (TLT/IEF/SHY/SPY/XLF/VIX).

    Returns headline + industry mix + underneath + tape + raw narrative.
    Does not interpret — surfaces the data so judgment happens in conversation.

    Requires [fred] + [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    bls_client = _bls(ctx)

    # Series specs: (id, limit). 13 obs needed for AHE YoY; 3 elsewhere is plenty
    # for MoM + 1-prior context.
    headline_specs = [("PAYEMS", 3), ("UNRATE", 3), ("CES0500000003", 13)]
    underneath_specs = [
        ("U6RATE", 3),
        ("CIVPART", 3),
        ("EMRATIO", 3),
        ("AWHAETP", 3),
        ("LNS12032194", 3),  # Part-time for economic reasons (level)
        ("CE16OV", 3),  # Civilian Employment level (household survey, 16+)
        ("CLF16OV", 3),  # Civilian Labor Force level (for decimal U-3)
        ("UNEMPLOY", 3),  # Unemployed level (for decimal U-3)
    ]
    industry_specs = [(sid, 3) for sid, _ in _INDUSTRY_SERIES]
    series_specs = headline_specs + underneath_specs + industry_specs

    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, lim))
        for sid, lim in series_specs
    ]
    tasks = [
        bls_client.get(bls.EMPLOYMENT_SITUATION, bls.EmptyRequest()),
        tradier.get(t.QUOTES, t.GetQuotesRequest("TLT,IEF,SHY,SPY,XLF,VIX")),
        *fred_tasks,
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    warnings: list[str] = []
    bls_resp = results[0] if not isinstance(results[0], BaseException) else None
    if bls_resp is None:
        warnings.append(_exc_summary("BLS Employment Situation press release", results[0]))
    tape_resp = results[1] if not isinstance(results[1], BaseException) else None
    if tape_resp is None:
        warnings.append(_exc_summary("Tradier intraday quotes", results[1]))
    obs_by_id = _collect_fred_obs(results, series_specs, 2, warnings)

    payems = obs_by_id.get("PAYEMS", [])
    unrate = obs_by_id.get("UNRATE", [])
    ahe = obs_by_id.get("CES0500000003", [])

    nfp_mom = _mom_change(payems)  # already in thousands per FRED units
    nfp_prior = _mom_change(payems[1:]) if len(payems) >= 3 else None
    period = payems[0]["date"] if payems else "?"
    u3_latest = _latest(unrate)

    unemploy_lvl = _latest(obs_by_id.get("UNEMPLOY", []))
    clf_lvl = _latest(obs_by_id.get("CLF16OV", []))
    u3_decimal: float | None = (
        unemploy_lvl / clf_lvl * 100
        if unemploy_lvl is not None and clf_lvl is not None and clf_lvl > 0
        else None
    )

    ahe_latest = _latest(ahe)
    ahe_mom_pct = _mom_pct(ahe)
    ahe_yoy_pct = _yoy_pct(ahe)

    out: list[str] = []
    out.extend(_warnings_section(warnings))
    out.append("=== Headline ===")
    out.append(f"Period: {period}")
    if nfp_mom is not None:
        prior_str = f", prior {nfp_prior:+,.0f}K" if nfp_prior is not None else ""
        out.append(f"NFP: {nfp_mom:+,.0f}K{prior_str}")
    if u3_latest is not None:
        dec_str = f" (decimal: {u3_decimal:.2f}%)" if u3_decimal is not None else ""
        out.append(f"U-3 unemployment: {u3_latest:.1f}%{dec_str}")
    if ahe_latest is not None:
        mom = f", MoM {ahe_mom_pct:+.2f}%" if ahe_mom_pct is not None else ""
        yoy = f", YoY {ahe_yoy_pct:+.2f}%" if ahe_yoy_pct is not None else ""
        out.append(f"AHE (private): ${ahe_latest:.2f}{mom}{yoy}")

    # Industry mix
    out.append("")
    out.append("=== Industry mix (MoM change) ===")
    industry_rows: list[tuple[str, float]] = []
    for sid, label in _INDUSTRY_SERIES:
        chg = _mom_change(obs_by_id.get(sid, []))
        if chg is not None:
            industry_rows.append((label, chg))
    # Sort detail rows by absolute change desc; keep parent totals at end.
    detail = [r for r in industry_rows if not r[0].startswith("(")]
    parents = [r for r in industry_rows if r[0].startswith("(")]
    detail.sort(key=lambda r: abs(r[1]), reverse=True)
    for label, chg in detail + parents:
        pct_share = ""
        if nfp_mom and abs(nfp_mom) > 0 and not label.startswith("("):
            pct_share = f"  ({chg / nfp_mom * 100:+.0f}% of total NFP)"
        out.append(f"  {label:36s} {chg:+,.0f}K{pct_share}")

    # Underneath
    out.append("")
    out.append("=== Underneath (latest, prior in parens) ===")

    def _fmt_pct(sid: str, label: str) -> None:
        cur = _latest(obs_by_id.get(sid, []))
        prv = _prior(obs_by_id.get(sid, []))
        if cur is not None:
            prior_str = f" ({prv:.1f}% prior)" if prv is not None else ""
            out.append(f"  {label:36s} {cur:.1f}%{prior_str}")

    def _fmt_lvl(sid: str, label: str, unit: str = "K") -> None:
        cur = _latest(obs_by_id.get(sid, []))
        prv = _prior(obs_by_id.get(sid, []))
        if cur is not None:
            prior_str = f" ({prv:,.0f}{unit} prior)" if prv is not None else ""
            out.append(f"  {label:36s} {cur:,.0f}{unit}{prior_str}")

    _fmt_pct("U6RATE", "U-6 underemployment")
    _fmt_pct("CIVPART", "Labor force participation")
    _fmt_pct("EMRATIO", "Employment-population ratio")
    awh = _latest(obs_by_id.get("AWHAETP", []))
    awh_p = _prior(obs_by_id.get("AWHAETP", []))
    if awh is not None:
        prior_str = f" ({awh_p:.1f} prior)" if awh_p is not None else ""
        out.append(f"  {'Avg weekly hours (private)':36s} {awh:.1f}{prior_str}")
    _fmt_lvl("LNS12032194", "Part-time for econ reasons")
    # Household vs establishment divergence
    hh_emp_chg = _mom_change(obs_by_id.get("CE16OV", []))
    if hh_emp_chg is not None and nfp_mom is not None:
        out.append(
            f"  {'Household survey emp Δ':36s} {hh_emp_chg:+,.0f}K"
            f"  (vs PAYEMS {nfp_mom:+,.0f}K — divergence "
            f"{hh_emp_chg - nfp_mom:+,.0f}K)"
        )

    # Tape
    out.append("")
    out.append("=== Tape (intraday) ===")
    if tape_resp and tape_resp.quotes:
        for q in tape_resp.quotes:
            sym = q.get("symbol", "")
            last = q.get("last")
            chg_pct = q.get("change_percentage")
            chg = q.get("change")
            if last is None:
                continue
            if sym == "VIX":
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg:+.2f})")
            else:
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg_pct:+.2f}%)")
    else:
        out.append("  (tape unavailable)")

    # Narrative
    out.append("")
    out.append("=== BLS press release narrative ===")
    if bls_resp and bls_resp.text:
        out.append(bls_resp.text)
    else:
        out.append("(BLS press release unavailable)")

    return "\n".join(out)


# CPI components — order: headline-adjacent, then major segments, then subcategories.
# All series are seasonally-adjusted index levels; MoM/YoY computed from the levels.
_CPI_MAJOR: list[tuple[str, str]] = [
    ("CPIENGSL", "Energy"),
    ("CPIUFDSL", "Food"),
    ("CUSR0000SAH1", "Shelter"),
    ("CUSR0000SAS", "Services"),
    ("CUSR0000SAC", "Goods (commodities)"),
    ("CUSR0000SASLE", "Services less energy (supercore proxy)"),
]
_CPI_SUBCATEGORY: list[tuple[str, str]] = [
    ("CUSR0000SEHA", "Rent of primary residence"),
    ("CUSR0000SEHC01", "Owners' equivalent rent"),
    ("CUSR0000SETB01", "Gasoline"),
    ("CUSR0000SETA02", "Used cars & trucks"),
    ("CUSR0000SETA01", "New vehicles"),
    ("CUSR0000SAM2", "Medical care services"),
    ("CUSR0000SETG01", "Public transportation"),
]


@mcp.tool()
async def get_cpi_report_texture(ctx: Context) -> str:
    """Latest BLS Consumer Price Index: headline + texture beneath the headline.

    Aggregates the BLS CPI press release narrative (categories that increased/
    decreased, gasoline/shelter/food commentary) with FRED CPI series for the
    component breakdown (headline, core, major segments — energy, food, shelter,
    services, goods — and a services-less-energy supercore proxy) plus subcategory
    detail (rent, OER, gasoline, used cars, new vehicles, medical care, public
    transportation). Includes Tradier intraday quotes for rate-sensitive tape +
    TIP for inflation expectations.

    Returns headline + components + subcategories + tape + raw narrative.
    Does not interpret — surfaces the data so judgment happens in conversation.

    Requires [fred] + [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    bls_client = _bls(ctx)

    # All CPI series are index levels; need 13 obs to compute YoY.
    headline_specs = [("CPIAUCSL", 13), ("CPILFESL", 13)]
    component_specs = [(sid, 13) for sid, _ in _CPI_MAJOR + _CPI_SUBCATEGORY]
    series_specs = headline_specs + component_specs

    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, lim))
        for sid, lim in series_specs
    ]
    tasks = [
        bls_client.get(bls.CPI_RELEASE, bls.EmptyRequest()),
        tradier.get(t.QUOTES, t.GetQuotesRequest("TLT,IEF,SHY,SPY,XLF,TIP,VIX")),
        *fred_tasks,
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    warnings: list[str] = []
    bls_resp = results[0] if not isinstance(results[0], BaseException) else None
    if bls_resp is None:
        warnings.append(_exc_summary("BLS CPI press release", results[0]))
    tape_resp = results[1] if not isinstance(results[1], BaseException) else None
    if tape_resp is None:
        warnings.append(_exc_summary("Tradier intraday quotes", results[1]))
    obs_by_id = _collect_fred_obs(results, series_specs, 2, warnings)

    headline = obs_by_id.get("CPIAUCSL", [])
    core = obs_by_id.get("CPILFESL", [])
    period = headline[0]["date"] if headline else "?"

    out: list[str] = []
    out.extend(_warnings_section(warnings))
    out.append("=== Headline ===")
    out.append(f"Period: {period}")

    def _mom_yoy_line(obs: list[dict], label: str) -> None:
        mom = _mom_pct(obs)
        yoy = _yoy_pct(obs)
        prior_mom = _mom_pct(obs[1:]) if len(obs) >= 3 else None
        if mom is None and yoy is None:
            return
        prior_str = f" (prior MoM {prior_mom:+.2f}%)" if prior_mom is not None else ""
        mom_str = f"MoM {mom:+.2f}%" if mom is not None else "MoM —"
        yoy_str = f"YoY {yoy:+.2f}%" if yoy is not None else "YoY —"
        out.append(f"{label}: {mom_str} | {yoy_str}{prior_str}")

    _mom_yoy_line(headline, "CPI (all items)")
    _mom_yoy_line(core, "Core CPI (ex food/energy)")

    # Major components
    out.append("")
    out.append("=== Major components (MoM, YoY) ===")
    for sid, label in _CPI_MAJOR:
        obs = obs_by_id.get(sid, [])
        mom = _mom_pct(obs)
        yoy = _yoy_pct(obs)
        if mom is None and yoy is None:
            continue
        mom_str = f"MoM {mom:+.2f}%" if mom is not None else "MoM —"
        yoy_str = f"YoY {yoy:+.2f}%" if yoy is not None else "YoY —"
        out.append(f"  {label:42s} {mom_str:14s} {yoy_str}")

    # Subcategory detail
    out.append("")
    out.append("=== Subcategory detail (MoM) ===")
    for sid, label in _CPI_SUBCATEGORY:
        mom = _mom_pct(obs_by_id.get(sid, []))
        if mom is None:
            continue
        out.append(f"  {label:36s} {mom:+.2f}%")

    # Tape
    out.append("")
    out.append("=== Tape (intraday) ===")
    if tape_resp and tape_resp.quotes:
        for q in tape_resp.quotes:
            sym = q.get("symbol", "")
            last = q.get("last")
            chg_pct = q.get("change_percentage")
            chg = q.get("change")
            if last is None:
                continue
            if sym == "VIX":
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg:+.2f})")
            else:
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg_pct:+.2f}%)")
    else:
        out.append("  (tape unavailable)")

    # Narrative
    out.append("")
    out.append("=== BLS press release narrative ===")
    if bls_resp and bls_resp.text:
        out.append(bls_resp.text)
    else:
        out.append("(BLS CPI press release unavailable)")

    return "\n".join(out)


@mcp.tool()
async def get_market_regime(ctx: Context) -> str:
    """Get current market regime classification with a synthesized verdict.

    Aggregates Tradier (VIX quotes + history, SPY/IWM technicals, 11 SPDR
    sector ETF histories), FRED (yield curve, fed funds, HY credit spreads),
    and TastyTrade (IV enrichment) into a single regime verdict + dimensional
    labels.

    Output starts with a verdict line synthesized from all dimensions:
    - Crash Active: vol Crisis (VIX backwardation or >=35) — gates Trigger 2
      of the structural tail-hedge program (harvest tranches)
    - Pre-Crash Watch: vol Elevated + (tape Fast OR credit Widening), or
      vol Normal + (tape Fast AND credit Widening)
    - Recovery: vol Elevated + Broadening breadth + Risk-On
    - Bear Setup: bear_score >= 3 (Downtrend / Narrowing / Risk-Off /
      un-inversion trap×2 / semi divergence)
    - Late Cycle: warnings emerging (Inverted / Narrowing / Rotation /
      un-inversion trap) but trend still Uptrend or Sideways
    - Expansion: Uptrend + Healthy/Broadening + Risk-On
    - Mixed: signals don't cohere

    Dimensional labels surfaced below the verdict:
    - Volatility, Trend, Breadth, Macro, Sectors (existing)
    - Credit: Widening / Stable / Tightening (HY OAS 5-day delta)
    - Tape Speed: Fast / Normal (SPY 5d return + VIX 5d %change)
    - Sentiment: Capitulation / Fearful / Neutral / Stretched / Greedy
      (CBOE equity p/c + NAAIM exposure + AAII bull-bear, contrarian polarity).
      NAAIM is always available (httpx XLSX); CBOE p/c and AAII require
      Playwright — if it didn't launch, the dimension still scores from
      whichever inputs are available.
    - Positioning: Crowded/Stretched Long / Mixed / Crowded/Stretched Short / Neutral
      (CFTC COT 52w z-score across SPX, NDX, VIX, 10Y, Gold, WTI; contrarian
      polarity — crowded long = bearish-forward, crowded short = squeeze risk).
    - Policy: Hold Priced / Cut Priced / Hike Priced / Cut Bias / Hike Bias /
      Uncertain — path-aware classifier built from three Polymarket event
      classes under the `fed` tag:
        1. "Fed Decision in <month>?" — next-meeting hold/cut/hike (headline)
        2. "Fed rate hike by ...?" / "...cut by..." — cumulative path by month
        3. "What will the Fed rate be at the end of <year>?" — year-end mode
      When the next meeting is Hold Priced, the label adds a tail qualifier
      ("Hawkish Tail" / "Dovish Tail" / "Balanced Tails") whenever the
      cumulative rails diverge by ≥10pp. Detail string surfaces the latest
      hike-by / cut-by readings and the year-end modal rate.
    - ⚠ Extended (verdict=Expansion only): fires when 2+ of RSI>70,
      sector dispersion>25pp 30d, SPY 5d>+3% — mean-reversion warning,
      not a verdict change
    - ⚠ Sentiment: fires when sentiment hits Greedy or Capitulation —
      strong contrarian signal worth flagging next to the verdict

    Requires [fred] and [tradier] sections in ~/.tradingrc.
    TastyTrade and sentiment are optional enrichment.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    tt_client = ctx.lifespan_context.get("tastytrade")
    sentiment_client = _sentiment(ctx)
    cftc_client = _cftc(ctx)
    polymarket_client = _polymarket(ctx)
    naaim_client = _naaim(ctx)

    start = _year_ago(date.today()).isoformat()
    tasks: list = [
        tradier.get(t.QUOTES, t.GetQuotesRequest("VIX,VIX3M")),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("T10Y2Y", 130)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 2)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("BAMLH0A0HYM2", 30)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("VIX", "daily", start=start)),
    ]
    sector_offset = len(tasks)

    for sym in HISTORY_SYMBOLS:
        tasks.append(tradier.get(t.HISTORY, t.GetHistoryRequest(sym, "daily", start=start)))

    tt_idx = None
    if tt_client:
        tt_idx = len(tasks)
        tasks.append(tt_client.get(tt.MARKET_METRICS, tt.MarketMetricsRequest("SPY")))

    cboe_idx: int | None = None
    aaii_idx: int | None = None
    if sentiment_client is not None:
        cboe_idx = len(tasks)
        tasks.append(sentiment_client.get(sentiment.CBOE_EQUITY_PC, sentiment.EmptyRequest()))
        aaii_idx = len(tasks)
        tasks.append(sentiment_client.get(sentiment.AAII_SENTIMENT, sentiment.EmptyRequest()))

    naaim_idx = len(tasks)
    tasks.append(naaim_client.get_history())

    cftc_keys = list(cftc.CONTRACTS.keys())
    cftc_offset = len(tasks)
    for key in cftc_keys:
        report_key, pattern, _ = cftc.CONTRACTS[key]
        tasks.append(cftc_client.get(cftc.REPORTS[report_key], cftc.GetCotRequest(pattern)))

    fed_events_idx = len(tasks)
    # limit=40 keeps room for both per-meeting and calendar-rollup events
    # (`Fed rate hike by ...?`, `Fed rate cut by ...?`, year-end rate distribution)
    # under the same `fed` tag.
    tasks.append(
        polymarket_client.get(
            polymarket.LIST_EVENTS_BY_TAG,
            polymarket.ListEventsByTagRequest(tag_slug="fed", limit=40),
        )
    )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    def _ok(i: int):
        return results[i] if not isinstance(results[i], BaseException) else None

    vix_quotes_resp = _ok(0)
    spread_resp = _ok(1)
    ff_resp = _ok(2)
    credit_resp = _ok(3)
    vix_hist_resp = _ok(4)

    closes: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    for i, sym in enumerate(HISTORY_SYMBOLS):
        resp = _ok(sector_offset + i)
        if resp and resp.days:
            closes[sym] = [float(b["close"]) for b in resp.days]
            volumes[sym] = [float(b["volume"]) for b in resp.days]

    vix_closes: list[float] = []
    if vix_hist_resp and vix_hist_resp.days:
        vix_closes = [float(b["close"]) for b in vix_hist_resp.days]

    data: dict[str, str | None] = {}
    labels: dict[str, str | None] = {
        "volatility": None,
        "trend": None,
        "breadth": None,
        "macro": None,
        "sectors": None,
        "credit": None,
        "speed": None,
        "sentiment": None,
        "positioning": None,
        "policy": None,
    }

    vix_val: float | None = None
    vix3m_val: float | None = None
    if vix_quotes_resp and vix_quotes_resp.quotes:
        for q in vix_quotes_resp.quotes:
            sym = q.get("symbol", "")
            if sym == "VIX":
                vix_val = q.get("last")
            elif sym == "VIX3M":
                vix3m_val = q.get("last")
    if vix_val is not None:
        label, detail = regime.classify_volatility(vix_val, vix3m_val)
        labels["volatility"] = label
        data["Volatility"] = f"{label} ({detail})"

    spy_closes = closes.get("SPY", [])
    spy_volumes = volumes.get("SPY", [])
    spy_rsi: float | None = None
    if spy_closes:
        price = spy_closes[-1]
        rsi_vals = ta.rsi(spy_closes)
        sma50_vals = ta.sma(spy_closes, 50)
        sma200_vals = ta.sma(spy_closes, 200)
        spy_rsi = rsi_vals[-1]
        label, detail = regime.classify_trend(price, spy_rsi, sma50_vals[-1], sma200_vals[-1])
        labels["trend"] = label
        data["Trend"] = f"{label} ({detail})"

    iwm_closes = closes.get("IWM", [])
    xlu_closes = closes.get("XLU", [])
    xly_closes = closes.get("XLY", [])
    rsp_closes = closes.get("RSP", []) or None
    if spy_closes and iwm_closes and xlu_closes and xly_closes:
        label, detail = regime.classify_breadth(
            spy_closes,
            iwm_closes,
            spy_volumes,
            xlu_closes,
            xly_closes,
            rsp_closes=rsp_closes,
        )
        labels["breadth"] = label
        data["Breadth"] = f"{label} ({detail})"

    spread_observations = spread_resp.observations if spread_resp else []
    spread_val, _ = regime.parse_fred_value(spread_observations)
    ff_observations = ff_resp.observations if ff_resp else []
    ff_val, _ = regime.parse_fred_value(ff_observations)
    prev_ff_obs = ff_observations[1:] if len(ff_observations) > 1 else []
    prev_ff_val, _ = regime.parse_fred_value(prev_ff_obs)
    label, detail = regime.classify_macro(spread_val, ff_val, prev_ff_val)
    labels["macro"] = label
    data["Macro"] = f"{label} ({detail})"

    spread_history = []
    for obs in spread_observations:
        v = obs.get("value", ".")
        if v != ".":
            try:
                spread_history.append(float(v))
            except (ValueError, TypeError):
                pass
    trap_warning = regime.detect_uninversion_trap(spread_history, spread_val, ff_val, prev_ff_val)
    if trap_warning:
        data["⚠ Macro"] = trap_warning

    sector_closes = {sym: closes[sym] for sym in regime.SECTOR_ETFS if sym in closes}
    if len(sector_closes) >= 6:
        label, detail = regime.classify_sector_rotation(sector_closes)
        labels["sectors"] = label
        data["Sectors"] = f"{label} ({detail})"

    smh_closes = closes.get("SMH", [])
    semi_warning: str | None = None
    if smh_closes and spy_closes:
        semi_warning = regime.detect_semi_divergence(smh_closes, spy_closes)
        if semi_warning:
            data["⚠ Sectors"] = semi_warning

    credit_observations = credit_resp.observations if credit_resp else []
    credit_val, _ = regime.parse_fred_value(credit_observations)
    credit_history: list[float] = []
    for obs in credit_observations:
        v = obs.get("value", ".")
        if v != ".":
            try:
                credit_history.append(float(v))
            except (ValueError, TypeError):
                pass
    label, detail = regime.classify_credit(credit_val, credit_history)
    labels["credit"] = label
    data["Credit"] = f"{label} ({detail})"

    credit_trap_warning = regime.detect_credit_trap(credit_val, credit_history)
    if credit_trap_warning:
        data["⚠ Credit"] = credit_trap_warning

    if spy_closes or vix_closes:
        label, detail = regime.classify_tape_speed(spy_closes, vix_closes)
        labels["speed"] = label
        data["Tape Speed"] = f"{label} ({detail})"

    # Sentiment — CBOE and AAII via Playwright (optional); NAAIM via XLSX
    # client (always available, independent of Playwright).
    cboe_resp = _ok(cboe_idx) if cboe_idx is not None else None
    aaii_resp = _ok(aaii_idx) if aaii_idx is not None else None
    naaim_resp = _ok(naaim_idx)
    cboe_pc = cboe_resp.value if cboe_resp is not None else None
    naaim_val = naaim_resp.latest_exposure if naaim_resp is not None else None
    aaii_spread_val = aaii_resp.spread if aaii_resp is not None else None
    if any(v is not None for v in (cboe_pc, naaim_val, aaii_spread_val)):
        label, detail = regime.classify_sentiment(cboe_pc, naaim_val, aaii_spread_val)
        labels["sentiment"] = label
        data["Sentiment"] = f"{label} ({detail})"
        if label in ("Greedy", "Capitulation"):
            note = (
                "crowded long, bearish for forward returns"
                if label == "Greedy"
                else "capitulation tilt, bullish for forward returns"
            )
            data["⚠ Sentiment"] = f"{label} sentiment — strong contrarian signal ({note})"

    # Positioning (CFTC COT — 6 contracts)
    contract_zs: dict[str, float | None] = {}
    for i, key in enumerate(cftc_keys):
        cot_resp = _ok(cftc_offset + i)
        contract_zs[key] = cot_resp.z_score if cot_resp is not None else None
    if any(z is not None for z in contract_zs.values()):
        label, detail = regime.classify_positioning(contract_zs)
        labels["positioning"] = label
        data["Positioning"] = f"{label} ({detail})"
        if label in ("Crowded Long", "Crowded Short"):
            note = (
                "specs heavily long, bearish-forward fade signal"
                if label == "Crowded Long"
                else "specs heavily short, squeeze risk / bullish-forward"
            )
            data["⚠ Positioning"] = f"{label} — strong contrarian signal ({note})"

    # Policy — path-aware classifier. We pull all fed-tagged Polymarket events
    # and feed three classes into synthesize_policy_path:
    #   1. "Fed Decision in <month>?"            — next-meeting hold/cut/hike
    #   2. "Fed rate hike by ...?" / "...cut..." — cumulative path by month
    #   3. "What will the Fed rate be at the end of <year>?" — year-end dist.
    # The headline label adds a tail qualifier (Hawkish/Dovish/Balanced) when
    # the next meeting is Hold Priced but the cumulative rails diverge.
    fed_events_resp = _ok(fed_events_idx)
    next_fomc = None
    hike_by_event = None
    cut_by_event = None
    year_end_event = None
    if fed_events_resp is not None and fed_events_resp.events:
        per_meeting_candidates = []
        for ev in fed_events_resp.events:
            tl = ev.title.lower()
            if tl.startswith("fed decision in "):
                per_meeting_candidates.append(ev)
            elif tl.startswith("fed rate hike by"):
                hike_by_event = ev
            elif tl.startswith("fed rate cut by"):
                cut_by_event = ev
            elif tl.startswith("what will the fed rate be at the end of"):
                year_end_event = ev
        per_meeting_candidates.sort(key=lambda e: e.end_date or "9999-99-99")
        if per_meeting_candidates:
            next_fomc = per_meeting_candidates[0]
    if next_fomc is not None and next_fomc.outcomes:
        next_pairs = [(o.label, o.implied_prob) for o in next_fomc.outcomes]
        hike_pairs = (
            [(o.label, o.implied_prob) for o in hike_by_event.outcomes]
            if hike_by_event
            else None
        )
        cut_pairs = (
            [(o.label, o.implied_prob) for o in cut_by_event.outcomes]
            if cut_by_event
            else None
        )
        ye_pairs = (
            [(o.label, o.implied_prob) for o in year_end_event.outcomes]
            if year_end_event
            else None
        )
        label, detail = regime.synthesize_policy_path(
            next_pairs, hike_pairs, cut_pairs, ye_pairs
        )
        # Surface only the base label (without tail qualifier) to the verdict
        # synthesizer; the tail nuance lives in the detail string for humans.
        labels["policy"] = label.split(" — ")[0]
        meta = (
            f" — {next_fomc.title}, resolves {next_fomc.end_date}"
            if next_fomc.end_date
            else f" — {next_fomc.title}"
        )
        data["Policy"] = f"{label} ({detail}){meta}"

    tt_resp = _ok(tt_idx) if tt_idx is not None else None
    if tt_resp and tt_resp.items:
        item = tt_resp.items[0]
        iv_rank = item.get("tw-implied-volatility-index-rank")
        iv_pctl = item.get("implied-volatility-percentile")
        parts = []
        if iv_rank is not None:
            parts.append(f"IV Rank {float(iv_rank) * 100:.0f}%")
        if iv_pctl is not None:
            parts.append(f"IV Pctl {float(iv_pctl) * 100:.0f}%")
        if parts:
            data["IV Context"] = f"SPY {', '.join(parts)}"

    warnings: set[str] = set()
    if trap_warning:
        warnings.add("uninversion_trap")
    if semi_warning:
        warnings.add("semi_divergence")
    if credit_trap_warning:
        warnings.add("credit_trap")
    verdict, evidence = regime.synthesize_verdict(
        labels["volatility"],
        labels["trend"],
        labels["breadth"],
        labels["macro"],
        labels["sectors"],
        labels["credit"],
        labels["speed"],
        warnings,
    )

    if verdict == "Expansion" and spy_closes:
        is_extended, ext_detail = regime.classify_extended(spy_rsi, sector_closes, spy_closes)
        if is_extended:
            data["⚠ Extended"] = f"{ext_detail} — size down new entries"

    return f"## Market Regime\n\n**Verdict: {verdict}**  \n*Why: {evidence}*\n\n{kv_table(data)}"


def _parse_obs_dated(obs: list[dict]) -> tuple[list[date], list[float]]:
    """Parse FRED observations into (dates, values), oldest-first."""
    pairs: list[tuple[date, float]] = []
    for o in obs or []:
        v = o.get("value", ".")
        if v == ".":
            continue
        try:
            d = datetime.strptime(o["date"], "%Y-%m-%d").date()
            pairs.append((d, float(v)))
        except (ValueError, KeyError, TypeError):
            continue
    pairs.sort(key=lambda p: p[0])
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _parse_bars_dated(resp) -> tuple[list[date], list[float], list[float]]:
    """Parse Tradier history response into (dates, closes, volumes), oldest-first."""
    if not resp or not resp.days:
        return [], [], []
    pairs: list[tuple[date, float, float]] = []
    for bar in resp.days:
        try:
            d = datetime.strptime(bar["date"], "%Y-%m-%d").date()
            pairs.append((d, float(bar["close"]), float(bar.get("volume") or 0)))
        except (ValueError, KeyError, TypeError):
            continue
    pairs.sort(key=lambda p: p[0])
    return [p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs]


def _score_bear_at_asof(
    asof: date,
    *,
    spread: tuple[list[date], list[float]],
    ff: tuple[list[date], list[float]],
    credit: tuple[list[date], list[float]],
    dgs2: tuple[list[date], list[float]],
    dgs10: tuple[list[date], list[float]],
    dgs30: tuple[list[date], list[float]],
    vix_bars: tuple[list[date], list[float], list[float]],
    spy_bars: tuple[list[date], list[float], list[float]],
    iwm_bars: tuple[list[date], list[float], list[float]],
    xlu_bars: tuple[list[date], list[float], list[float]],
    xly_bars: tuple[list[date], list[float], list[float]],
    rsp_bars: tuple[list[date], list[float], list[float]],
    naaim_pairs: list[tuple[date, float]],
    dix_triplets: list[tuple[date, float, float]],
    cot_by_key: dict[str, list[tuple[date, float]]],
    factset_resp,
) -> float:
    """Re-score the composite at a historical as-of date using sliced inputs.

    Returns composite 0-10. Reuses every score_bear_* function so the math
    is identical to the live `Today` reading; only the inputs are sliced.
    """
    from bisect import bisect_right

    def _slice(dates: list[date], vals: list[float]) -> list[float]:
        return vals[: bisect_right(dates, asof)]

    def _slice2(
        dates: list[date], a: list[float], b: list[float]
    ) -> tuple[list[float], list[float]]:
        i = bisect_right(dates, asof)
        return a[:i], b[:i]

    # Curve
    spread_vals = _slice(*spread)
    ff_vals = _slice(*ff)
    ff_val = ff_vals[-1] if ff_vals else None
    prev_ff = ff_vals[-2] if len(ff_vals) > 1 else None
    spread_val = spread_vals[-1] if spread_vals else None
    dgs2_vals = _slice(*dgs2)
    dgs10_vals = _slice(*dgs10)
    dgs30_vals = _slice(*dgs30)

    def _curve_4w(vals: list[float]) -> float | None:
        if len(vals) < 21:
            return None
        return (vals[-1] - vals[-21]) * 100

    curve_label: str | None = None
    if dgs2_vals or dgs10_vals or dgs30_vals:
        curve_label, _ = regime.classify_curve_regime(
            _curve_4w(dgs2_vals), _curve_4w(dgs10_vals), _curve_4w(dgs30_vals)
        )
    uninversion = regime.detect_uninversion_trap(spread_vals, spread_val, ff_val, prev_ff)
    score_curve = regime.score_bear_curve(curve_label, uninversion, spread_vals)

    # Valuation (ERP) — FactSet PDF is current-snapshot; available only at today
    score_val = regime.BearScoreComponent(
        "Valuation (ERP)", 0.0, "Unknown", "PDF not historized", False
    )

    # Credit
    credit_vals = _slice(*credit)
    current_credit = credit_vals[-1] if credit_vals else None
    credit_hist_newest = list(reversed(credit_vals[-30:]))
    credit_trap = regime.detect_credit_trap(current_credit, credit_hist_newest)
    score_cred = regime.score_bear_credit(current_credit, credit_hist_newest, credit_trap)

    # Positioning (COT)
    contract_zs: dict[str, float | None] = {}
    for key, pairs in cot_by_key.items():
        idx = bisect_right([p[0] for p in pairs], asof)
        sample = [p[1] for p in pairs[max(0, idx - 53) : idx]]
        if len(sample) < 8:
            contract_zs[key] = None
            continue
        mu = sum(sample) / len(sample)
        sd = (sum((s - mu) ** 2 for s in sample) / len(sample)) ** 0.5
        contract_zs[key] = (sample[-1] - mu) / sd if sd > 0 else None
    positioning_label: str | None = None
    if any(z is not None for z in contract_zs.values()):
        positioning_label, _ = regime.classify_positioning(contract_zs)
    score_pos = regime.score_bear_positioning(positioning_label)

    # Sentiment — NAAIM only at as-of (CBOE p/c, AAII are current-snapshot only)
    naaim_idx = bisect_right([p[0] for p in naaim_pairs], asof)
    naaim_val = naaim_pairs[naaim_idx - 1][1] if naaim_idx > 0 else None
    sentiment_label: str | None = None
    if naaim_val is not None:
        sentiment_label, _ = regime.classify_sentiment(None, naaim_val, None)
    score_sent = regime.score_bear_sentiment(sentiment_label)

    # Volatility
    vix_dates, vix_closes_full, _ = vix_bars
    vix_closes_sl = _slice(vix_dates, vix_closes_full)
    vix_val = vix_closes_sl[-1] if vix_closes_sl else None
    score_v = regime.score_bear_volatility(vix_val, None, vix_closes_sl)

    # Technicals
    spy_dates, spy_closes_full, spy_vols_full = spy_bars
    spy_closes_sl, spy_vols_sl = _slice2(spy_dates, spy_closes_full, spy_vols_full)
    spy_rsi: float | None = None
    sma200: float | None = None
    if spy_closes_sl:
        rsi_vals = ta.rsi(spy_closes_sl)
        sma200_vals = ta.sma(spy_closes_sl, 200)
        if rsi_vals:
            spy_rsi = rsi_vals[-1]
        if sma200_vals:
            sma200 = sma200_vals[-1]
    score_tech = regime.score_bear_technicals(spy_closes_sl, spy_vols_sl, spy_rsi, sma200)

    # Breadth
    _, iwm_closes_sl, _ = (
        (iwm_bars[0], _slice(iwm_bars[0], iwm_bars[1]), []) if iwm_bars[0] else ([], [], [])
    )
    _, xlu_closes_sl, _ = (
        (xlu_bars[0], _slice(xlu_bars[0], xlu_bars[1]), []) if xlu_bars[0] else ([], [], [])
    )
    _, xly_closes_sl, _ = (
        (xly_bars[0], _slice(xly_bars[0], xly_bars[1]), []) if xly_bars[0] else ([], [], [])
    )
    rsp_closes_sl: list[float] | None = None
    if rsp_bars[0]:
        rsp_closes_sl = _slice(rsp_bars[0], rsp_bars[1]) or None
    breadth_label: str | None = None
    breadth_detail: str | None = None
    if spy_closes_sl and iwm_closes_sl and xlu_closes_sl and xly_closes_sl:
        breadth_label, breadth_detail = regime.classify_breadth(
            spy_closes_sl,
            iwm_closes_sl,
            spy_vols_sl,
            xlu_closes_sl,
            xly_closes_sl,
            rsp_closes=rsp_closes_sl,
        )
    score_b = regime.score_bear_breadth(breadth_label, breadth_detail)

    # Dealer flow
    if not dix_triplets:
        score_d = regime.BearScoreComponent(
            "Dealer Flow (DIX/GEX)", 0.0, "Unknown", "no DIX history", False
        )
    else:
        idx = bisect_right([t[0] for t in dix_triplets], asof)
        if idx == 0:
            score_d = regime.BearScoreComponent(
                "Dealer Flow (DIX/GEX)", 0.0, "Unknown", "pre-SqueezeMetrics history", False
            )
        else:
            current_dix = dix_triplets[idx - 1][1]
            current_gex = dix_triplets[idx - 1][2]
            gex_hist = [t[2] for t in dix_triplets[max(0, idx - 252) : idx]]
            score_d = regime.score_bear_dealer_flow(current_dix, current_gex, gex_hist)

    components = [
        score_curve,
        score_val,
        score_cred,
        score_pos,
        score_sent,
        score_v,
        score_tech,
        score_b,
        score_d,
    ]
    composite, _, _, _ = regime.synthesize_bear_regime(components)
    return composite


def _tier_for_score(score: float) -> str:
    if score < 2.0:
        return "Clear"
    if score < 4.0:
        return "Watchful"
    if score < 6.0:
        return "Building"
    if score < 7.0:
        return "Defensive"
    return "Crisis"


def _tier_rank(tier: str) -> int:
    return {"Clear": 0, "Watchful": 1, "Building": 2, "Defensive": 3, "Crisis": 4}.get(
        tier.split(" (")[0], -1
    )


def _bear_regime_trend(
    current_composite: float,
    current_tier: str,
    *,
    spread_obs,
    ff_obs,
    credit_obs,
    dgs2_obs,
    dgs10_obs,
    dgs30_obs,
    vix_closes: list[float],
    spy_hist,
    iwm_hist,
    xlu_hist,
    xly_hist,
    rsp_hist,
    naaim_entries,
    dix_rows,
    cot_weeklies: dict,
    factset_resp,
) -> list[str]:
    """Build the trend section lines: Δ7d, Δ30d, last-below-tier lookback.

    Uses already-fetched historized inputs (re-sliced per as-of date) so no
    additional network calls. Approximations: CBOE p/c, AAII, FactSet ERP
    are current-only — at historical as-of dates these dims fall through to
    available=False and are excluded from the normalized composite.
    """
    # Parse everything into dated form once
    spread = _parse_obs_dated(spread_obs)
    ff = _parse_obs_dated(ff_obs)
    credit = _parse_obs_dated(credit_obs)
    dgs2 = _parse_obs_dated(dgs2_obs)
    dgs10 = _parse_obs_dated(dgs10_obs)
    dgs30 = _parse_obs_dated(dgs30_obs)
    # VIX in the live tool comes from history; reuse the closes list with synthetic dates
    # by matching against SPY bar dates (same trading calendar). Use SPY's dates.
    spy_bars = _parse_bars_dated(spy_hist)
    vix_dates_aligned: list[date]
    if len(vix_closes) == len(spy_bars[0]):
        vix_dates_aligned = spy_bars[0]
    else:
        # Length mismatch (likely fewer VIX history days); align to the tail of SPY dates
        n = min(len(vix_closes), len(spy_bars[0]))
        vix_dates_aligned = spy_bars[0][-n:]
        vix_closes = vix_closes[-n:]
    vix_bars: tuple[list[date], list[float], list[float]] = (
        vix_dates_aligned,
        list(vix_closes),
        [],
    )
    iwm_bars = _parse_bars_dated(iwm_hist)
    xlu_bars = _parse_bars_dated(xlu_hist)
    xly_bars = _parse_bars_dated(xly_hist)
    rsp_bars = _parse_bars_dated(rsp_hist)
    naaim_pairs = sorted(((e.week_ending, e.exposure) for e in naaim_entries), key=lambda p: p[0])
    dix_triplets = sorted(((r.date, r.dix, r.gex) for r in dix_rows), key=lambda p: p[0])
    cot_by_key: dict[str, list[tuple[date, float]]] = {}
    from trading_clients.endpoints.cftc import _spec_net

    for key, resp in cot_weeklies.items():
        if resp is None:
            cot_by_key[key] = []
            continue
        pairs: list[tuple[date, float]] = []
        for rec in resp.weekly:
            raw = rec.get("report_date_as_yyyy_mm_dd", "")[:10]
            try:
                d = datetime.strptime(raw, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            n = _spec_net(rec)
            if n is None:
                continue
            pairs.append((d, n))
        pairs.sort(key=lambda p: p[0])
        cot_by_key[key] = pairs

    # Pick "today" as the latest SPY bar date (anchors to actual trading calendar)
    if not spy_bars[0]:
        return []
    today_anchor = spy_bars[0][-1]

    def _score_at(asof: date) -> float:
        return _score_bear_at_asof(
            asof,
            spread=spread,
            ff=ff,
            credit=credit,
            dgs2=dgs2,
            dgs10=dgs10,
            dgs30=dgs30,
            vix_bars=vix_bars,
            spy_bars=spy_bars,
            iwm_bars=iwm_bars,
            xlu_bars=xlu_bars,
            xly_bars=xly_bars,
            rsp_bars=rsp_bars,
            naaim_pairs=naaim_pairs,
            dix_triplets=dix_triplets,
            cot_by_key=cot_by_key,
            factset_resp=factset_resp,
        )

    score_7d = _score_at(today_anchor - timedelta(days=7))
    score_30d = _score_at(today_anchor - timedelta(days=30))
    delta_7d = current_composite - score_7d
    delta_30d = current_composite - score_30d

    lines: list[str] = []
    lines.append(
        f"(Δ7d: {delta_7d:+.1f} from {score_7d:.1f}, Δ30d: {delta_30d:+.1f} from {score_30d:.1f})"
    )

    # Last-below-tier lookback — walk back weekly up to 26 weeks (6 months)
    cur_rank = _tier_rank(current_tier)
    if cur_rank > 0:
        found_below: date | None = None
        prior_rank: int | None = None
        for weeks_back in range(7, 7 + 26 * 7, 7):
            asof = today_anchor - timedelta(days=weeks_back)
            sc = _score_at(asof)
            r = _tier_rank(_tier_for_score(sc))
            if r < cur_rank:
                found_below = asof
                prior_rank = r
                break
        if found_below is not None:
            days_in_tier = (today_anchor - found_below).days
            prior_tier_name = ["Clear", "Watchful", "Building", "Defensive", "Crisis"][
                prior_rank or 0
            ]
            lines.append("")
            lines.append(
                f"_Score has been at ≥ {current_tier.split(' (')[0]} for ≥{days_in_tier} days "
                f"(last {prior_tier_name} reading: {found_below})._"
            )
        else:
            lines.append("")
            lines.append(
                f"_Score has held at ≥ {current_tier.split(' (')[0]} for ≥182 days "
                f"(no lower reading in lookback window)._"
            )

    return lines


@mcp.tool()
async def get_bear_regime_score(ctx: Context) -> str:
    """Composite 0-10 bear-regime risk score across 9 dimensions.

    Aggregates yield curve regime, valuation (ERP), HY credit spreads,
    CFTC speculator positioning, retail/active-manager sentiment, VIX
    structure, SPY technicals, market-internals breadth (SPY/IWM +
    XLY/XLU + volume + SPY/RSP concentration), and SqueezeMetrics dealer
    flow (DIX/GEX) into a single 0-10 score with tier label and
    per-dimension breakdown.

    Tiers:
      0-1.99 Clear     — no special action, normal accumulation OK
      2-3.99 Watchful  — verify tail hedge sized, prefer CCs on extended winners
      4-5.99 Building  — pause new entries in high-multiple names
      6-6.99 Defensive — trim high-multiple, raise tail hedge delta, write CCs on winners
      7-10   Crisis    — freeze new entries, max tail hedge, sell rallies

    Score is *normalized over available dimensions* — missing data is
    excluded rather than counted as Safe. When <60% of dimensions are
    available the tier line is suffixed "(incomplete data)" so the reader
    can flag low-confidence reads.

    Designed as a decision checkpoint for `/briefing` (top section) and
    `/review` (action plan trigger). Position cross-reference logic lives
    in the skills, not this tool — the tool emits the macro read, the
    skill decides which positions are exposed.

    Breadth reuses classify_breadth (the same definition surfaced by
    get_market_regime) — SPY/IWM divergence + XLY/XLU rotation + SPY
    volume trend + SPY/RSP equal-weight concentration — rather than
    introducing a competing "% SPX above 200dma" measure that would
    require iterating constituents. v1 weights are educated guesses;
    expect to retune after a few months of live observation against
    historical episodes.

    Requires [fred] and [tradier] sections in ~/.tradingrc. FactSet,
    CFTC, NAAIM, SqueezeMetrics are no-auth public sources;
    [sentiment] (CBOE p/c + AAII) requires Playwright.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    factset_client = _factset(ctx)
    sentiment_client = _sentiment(ctx)
    cftc_client = _cftc(ctx)
    naaim_client = _naaim(ctx)
    squeeze_client = _squeeze_metrics(ctx)

    start = _year_ago(date.today()).isoformat()
    tasks: list = [
        # 0: VIX + VIX3M quotes (vol regime + backwardation)
        tradier.get(t.QUOTES, t.GetQuotesRequest("VIX,VIX3M")),
        # 1: T10Y2Y spread history (for un-inversion trap + deep-inversion check)
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("T10Y2Y", 130)),
        # 2: Fed funds (for un-inversion trap direction)
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 2)),
        # 3: HY OAS (credit spread regime)
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("BAMLH0A0HYM2", 30)),
        # 4-6: DGS2/10/30 for curve regime 4w change classification
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS2", 80)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS10", 80)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS30", 80)),
        # 7: VIX history (complacency tier needs 60d avg)
        tradier.get(t.HISTORY, t.GetHistoryRequest("VIX", "daily", start=start)),
        # 8: SPY history (technicals — SMA200, RSI, distribution days + breadth)
        tradier.get(t.HISTORY, t.GetHistoryRequest("SPY", "daily", start=start)),
        # 9: FactSet weekly PDF (forward 12M P/E for ERP)
        factset_client.get_earnings_insight(),
        # 10: SqueezeMetrics DIX/GEX history
        squeeze_client.get(squeeze_metrics.DIX_HISTORY, squeeze_metrics.EmptyRequest()),
        # 11: NAAIM exposure (one of three sentiment inputs)
        naaim_client.get_history(),
        # 12-15: IWM / XLU / XLY / RSP for breadth (SPY/IWM divergence + XLY/XLU
        # rotation + SPY/RSP equal-weight concentration)
        tradier.get(t.HISTORY, t.GetHistoryRequest("IWM", "daily", start=start)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("XLU", "daily", start=start)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("XLY", "daily", start=start)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("RSP", "daily", start=start)),
    ]

    cboe_idx: int | None = None
    aaii_idx: int | None = None
    if sentiment_client is not None:
        cboe_idx = len(tasks)
        tasks.append(sentiment_client.get(sentiment.CBOE_EQUITY_PC, sentiment.EmptyRequest()))
        aaii_idx = len(tasks)
        tasks.append(sentiment_client.get(sentiment.AAII_SENTIMENT, sentiment.EmptyRequest()))

    cftc_keys = list(cftc.CONTRACTS.keys())
    cftc_offset = len(tasks)
    for key in cftc_keys:
        report_key, pattern, _ = cftc.CONTRACTS[key]
        tasks.append(cftc_client.get(cftc.REPORTS[report_key], cftc.GetCotRequest(pattern)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    def _ok(i: int):
        return results[i] if not isinstance(results[i], BaseException) else None

    # Aggregate any fetch failures as warnings; missing dims fall through to
    # `available=False` via the scoring functions.
    warnings: list[str] = []
    source_names = {
        0: "Tradier VIX quotes",
        1: "FRED T10Y2Y",
        2: "FRED FEDFUNDS",
        3: "FRED HY OAS",
        4: "FRED DGS2",
        5: "FRED DGS10",
        6: "FRED DGS30",
        7: "Tradier VIX history",
        8: "Tradier SPY history",
        9: "FactSet Earnings Insight",
        10: "SqueezeMetrics DIX/GEX",
        11: "NAAIM history",
        12: "Tradier IWM history",
        13: "Tradier XLU history",
        14: "Tradier XLY history",
        15: "Tradier RSP history",
    }
    if cboe_idx is not None:
        source_names[cboe_idx] = "CBOE equity p/c"
    if aaii_idx is not None:
        source_names[aaii_idx] = "AAII sentiment"
    for i, key in enumerate(cftc_keys):
        source_names[cftc_offset + i] = f"CFTC COT {key}"
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(source_names.get(i, f"task {i}"), r))

    # === Parse fetched data ===
    vix_quotes_resp = _ok(0)
    spread_resp = _ok(1)
    ff_resp = _ok(2)
    credit_resp = _ok(3)
    dgs2_resp = _ok(4)
    dgs10_resp = _ok(5)
    dgs30_resp = _ok(6)
    vix_hist_resp = _ok(7)
    spy_hist_resp = _ok(8)
    factset_resp = _ok(9)
    squeeze_resp = _ok(10)
    naaim_resp = _ok(11)
    iwm_hist_resp = _ok(12)
    xlu_hist_resp = _ok(13)
    xly_hist_resp = _ok(14)
    rsp_hist_resp = _ok(15)

    def _obs_history(obs: list[dict]) -> list[float]:
        out: list[float] = []
        for o in obs:
            v = o.get("value", ".")
            if v == ".":
                continue
            try:
                out.append(float(v))
            except (ValueError, TypeError):
                pass
        return out

    def _curve_4w_change(obs: list[dict]) -> float | None:
        cur = _obs_value_at(obs, 0)
        prior = _obs_value_at(obs, 20) if len(obs) > 20 else None
        if cur is None or prior is None:
            return None
        return (cur - prior) * 100

    # === Volatility ===
    vix_val: float | None = None
    vix3m_val: float | None = None
    if vix_quotes_resp and vix_quotes_resp.quotes:
        for q in vix_quotes_resp.quotes:
            sym = q.get("symbol", "")
            if sym == "VIX":
                vix_val = q.get("last")
            elif sym == "VIX3M":
                vix3m_val = q.get("last")
    vix_closes: list[float] = []
    if vix_hist_resp and vix_hist_resp.days:
        vix_closes = [float(b["close"]) for b in vix_hist_resp.days]
    score_vol = regime.score_bear_volatility(vix_val, vix3m_val, vix_closes)

    # === Curve ===
    spread_obs = spread_resp.observations if spread_resp else []
    spread_history = _obs_history(spread_obs)
    spread_val, _ = regime.parse_fred_value(spread_obs)
    ff_obs = ff_resp.observations if ff_resp else []
    ff_val, _ = regime.parse_fred_value(ff_obs)
    prev_ff_val, _ = regime.parse_fred_value(ff_obs[1:] if len(ff_obs) > 1 else [])
    uninversion_warning = regime.detect_uninversion_trap(
        spread_history, spread_val, ff_val, prev_ff_val
    )
    dgs2_obs = dgs2_resp.observations if dgs2_resp else []
    dgs10_obs = dgs10_resp.observations if dgs10_resp else []
    dgs30_obs = dgs30_resp.observations if dgs30_resp else []
    curve_label: str | None = None
    if dgs2_obs or dgs10_obs or dgs30_obs:
        curve_label, _ = regime.classify_curve_regime(
            _curve_4w_change(dgs2_obs),
            _curve_4w_change(dgs10_obs),
            _curve_4w_change(dgs30_obs),
        )
    score_curve = regime.score_bear_curve(curve_label, uninversion_warning, spread_history)

    # === Valuation (ERP) ===
    erp_bps: float | None = None
    if factset_resp and dgs10_obs:
        fwd_pe = factset_resp.forward_pe
        dgs10_val, _ = regime.parse_fred_value(dgs10_obs)
        if fwd_pe and dgs10_val is not None:
            earnings_yield = 100.0 / fwd_pe
            erp_bps = (earnings_yield - dgs10_val) * 100
    score_valuation = regime.score_bear_valuation(erp_bps)

    # === Credit ===
    credit_obs = credit_resp.observations if credit_resp else []
    credit_val, _ = regime.parse_fred_value(credit_obs)
    credit_history = _obs_history(credit_obs)
    credit_trap = regime.detect_credit_trap(credit_val, credit_history)
    score_credit = regime.score_bear_credit(credit_val, credit_history, credit_trap)

    # === Sentiment ===
    cboe_resp = _ok(cboe_idx) if cboe_idx is not None else None
    aaii_resp = _ok(aaii_idx) if aaii_idx is not None else None
    cboe_pc = cboe_resp.value if cboe_resp is not None else None
    naaim_val = naaim_resp.latest_exposure if naaim_resp is not None else None
    aaii_spread_val = aaii_resp.spread if aaii_resp is not None else None
    sentiment_label: str | None = None
    if any(v is not None for v in (cboe_pc, naaim_val, aaii_spread_val)):
        sentiment_label, _ = regime.classify_sentiment(cboe_pc, naaim_val, aaii_spread_val)
    score_sentiment = regime.score_bear_sentiment(sentiment_label)

    # === Positioning ===
    contract_zs: dict[str, float | None] = {}
    for i, key in enumerate(cftc_keys):
        cot_resp = _ok(cftc_offset + i)
        contract_zs[key] = cot_resp.z_score if cot_resp is not None else None
    positioning_label: str | None = None
    if any(z is not None for z in contract_zs.values()):
        positioning_label, _ = regime.classify_positioning(contract_zs)
    score_positioning = regime.score_bear_positioning(positioning_label)

    # === Technicals ===
    spy_closes: list[float] = []
    spy_volumes: list[float] = []
    if spy_hist_resp and spy_hist_resp.days:
        spy_closes = [float(b["close"]) for b in spy_hist_resp.days]
        spy_volumes = [float(b["volume"]) for b in spy_hist_resp.days]
    spy_rsi: float | None = None
    sma200: float | None = None
    if spy_closes:
        rsi_vals = ta.rsi(spy_closes)
        sma200_vals = ta.sma(spy_closes, 200)
        if rsi_vals:
            spy_rsi = rsi_vals[-1]
        if sma200_vals:
            sma200 = sma200_vals[-1]
    score_technicals = regime.score_bear_technicals(spy_closes, spy_volumes, spy_rsi, sma200)

    # === Breadth ===
    # Reuses classify_breadth: SPY/IWM divergence + XLY/XLU rotation + SPY
    # volume trend + SPY/RSP equal-weight concentration.
    iwm_closes: list[float] = []
    xlu_closes: list[float] = []
    xly_closes: list[float] = []
    rsp_closes: list[float] = []
    if iwm_hist_resp and iwm_hist_resp.days:
        iwm_closes = [float(b["close"]) for b in iwm_hist_resp.days]
    if xlu_hist_resp and xlu_hist_resp.days:
        xlu_closes = [float(b["close"]) for b in xlu_hist_resp.days]
    if xly_hist_resp and xly_hist_resp.days:
        xly_closes = [float(b["close"]) for b in xly_hist_resp.days]
    if rsp_hist_resp and rsp_hist_resp.days:
        rsp_closes = [float(b["close"]) for b in rsp_hist_resp.days]
    breadth_label: str | None = None
    breadth_detail: str | None = None
    if spy_closes and iwm_closes and xlu_closes and xly_closes:
        breadth_label, breadth_detail = regime.classify_breadth(
            spy_closes,
            iwm_closes,
            spy_volumes,
            xlu_closes,
            xly_closes,
            rsp_closes=rsp_closes or None,
        )
    score_breadth = regime.score_bear_breadth(breadth_label, breadth_detail)

    # === Dealer flow ===
    current_dix: float | None = None
    current_gex: float | None = None
    gex_history: list[float] = []
    if squeeze_resp and squeeze_resp.rows:
        latest = squeeze_resp.rows[-1]
        current_dix = latest.dix
        current_gex = latest.gex
        gex_history = [r.gex for r in squeeze_resp.rows[-252:]]
    score_dealer = regime.score_bear_dealer_flow(current_dix, current_gex, gex_history)

    components = [
        score_curve,
        score_valuation,
        score_credit,
        score_positioning,
        score_sentiment,
        score_vol,
        score_technicals,
        score_breadth,
        score_dealer,
    ]
    composite, tier, top_contributors, missing = regime.synthesize_bear_regime(components)

    # === Trend snapshots (Phase 4) ===
    # Re-score the composite at 7d-ago and 30d-ago using already-fetched
    # historized inputs. Walks back weekly to find when the score last sat
    # below the current tier — surfaces persistence vs whipsaw.
    trend_lines = _bear_regime_trend(
        composite,
        tier,
        spread_obs=spread_obs,
        ff_obs=ff_obs,
        credit_obs=credit_obs,
        dgs2_obs=dgs2_obs,
        dgs10_obs=dgs10_obs,
        dgs30_obs=dgs30_obs,
        vix_closes=vix_closes,
        spy_hist=spy_hist_resp,
        iwm_hist=iwm_hist_resp,
        xlu_hist=xlu_hist_resp,
        xly_hist=xly_hist_resp,
        rsp_hist=rsp_hist_resp,
        naaim_entries=naaim_resp.entries if naaim_resp is not None else [],
        dix_rows=squeeze_resp.rows if squeeze_resp is not None else [],
        cot_weeklies={k: _ok(cftc_offset + i) for i, k in enumerate(cftc_keys)},
        factset_resp=factset_resp,
    )

    # === Format output ===
    out: list[str] = []
    out.extend(_warnings_section(warnings))
    out.append("## Bear Regime Score")
    out.append("")
    headline = f"**{composite:.1f} / 10 — {tier}**"
    if trend_lines:
        # trend_lines[0] is the inline delta suffix; remaining entries are
        # block-level (persistence note).
        out.append(headline + " " + trend_lines[0].strip())
        for extra in trend_lines[1:]:
            out.append(extra)
    else:
        out.append(headline)
    out.append("")

    if top_contributors:
        out.append("**Top contributors:**")
        for c in top_contributors:
            out.append(f"- **{c.name}** ({c.score:.1f}, {c.label}) — {c.detail}")
        out.append("")
    else:
        out.append("*No dimensions firing — all available signals at Safe.*")
        out.append("")

    out.append("**All dimensions:**")
    rows: list[list[str]] = []
    for c in components:
        if c.available:
            rows.append([c.name, f"{c.score:.1f}", c.label, c.detail])
        else:
            rows.append([c.name, "—", "Unknown", c.detail])
    out.append(md_table(["Dimension", "Score", "Label", "Detail"], rows))

    if missing:
        out.append("")
        names = ", ".join(c.name for c in missing)
        out.append(f"*Missing: {names}*")

    return "\n".join(out)


# PCE component price indexes (level series; MoM/YoY computed from levels).
_PCE_COMPONENTS: list[tuple[str, str]] = [
    ("DSERRG3M086SBEA", "Services"),
    ("DGDSRG3M086SBEA", "Goods"),
]


async def _bea_pce_release(
    bea_client,
) -> tuple["bea.BeaReleaseResponse | None", list[str]]:
    """Two-step BEA fetch: discover the latest PCE release URL, then fetch it.

    Returns (response, warnings). On full success, warnings is []. Each step
    that fails contributes a warning so the caller can surface it.
    """
    warnings: list[str] = []
    try:
        idx = await bea_client.get(bea.CURRENT_RELEASES, bea.EmptyRequest())
    except Exception as e:
        warnings.append(_exc_summary("BEA current-releases index", e))
        return None, warnings
    if not idx.pce_release_path:
        warnings.append("BEA current-releases: no Personal Income and Outlays link found")
        return None, warnings
    try:
        resp = await bea_client.get(bea.PCE_RELEASE, bea.ReleasePathRequest(idx.pce_release_path))
        return resp, warnings
    except Exception as e:
        warnings.append(_exc_summary(f"BEA PCE release {idx.pce_release_path}", e))
        return None, warnings


@mcp.tool()
async def get_pce_report_texture(ctx: Context) -> str:
    """Latest BEA Personal Income and Outlays: headline + texture beneath the headline.

    Aggregates the BEA Personal Income and Outlays press release narrative
    (income drivers, goods vs services PCE breakdown, savings rate commentary)
    with FRED PCE series for the price texture (headline, core, supercore proxy
    — services excluding energy and housing — services price, goods price) and
    the spending/income texture (nominal PCE, real PCE, personal income, DPI,
    savings rate). Includes Tradier intraday quotes for rate-sensitive tape +
    TIP for inflation expectations.

    Returns headline + spending/income + components + tape + raw narrative.
    Does not interpret — surfaces the data so judgment happens in conversation.

    Requires [fred] + [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    bea_client = _bea(ctx)

    headline_specs = [
        ("PCEPI", 13),
        ("PCEPILFE", 13),
        ("IA001260M", 13),  # Supercore: services ex housing & energy
    ]
    spending_specs = [
        ("PCE", 13),  # Nominal PCE
        ("PCEC96", 13),  # Real PCE
        ("PI", 13),  # Personal Income
        ("DSPI", 13),  # Disposable Personal Income
        ("PSAVERT", 3),  # Savings Rate (already %)
    ]
    component_specs = [(sid, 13) for sid, _ in _PCE_COMPONENTS]
    series_specs = headline_specs + spending_specs + component_specs

    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, lim))
        for sid, lim in series_specs
    ]
    tasks = [
        _bea_pce_release(bea_client),
        tradier.get(t.QUOTES, t.GetQuotesRequest("TLT,IEF,SHY,SPY,XLF,TIP,VIX")),
        *fred_tasks,
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    warnings: list[str] = []
    bea_bundle = results[0]
    if isinstance(bea_bundle, BaseException):
        warnings.append(_exc_summary("BEA Personal Income and Outlays (unexpected)", bea_bundle))
        bea_resp = None
    else:
        bea_resp, bea_warnings = bea_bundle
        warnings.extend(bea_warnings)
    tape_resp = results[1] if not isinstance(results[1], BaseException) else None
    if tape_resp is None:
        warnings.append(_exc_summary("Tradier intraday quotes", results[1]))
    obs_by_id = _collect_fred_obs(results, series_specs, 2, warnings)

    pce_pi = obs_by_id.get("PCEPI", [])
    period = pce_pi[0]["date"] if pce_pi else "?"

    out: list[str] = []
    out.extend(_warnings_section(warnings))
    out.append("=== Headline ===")
    out.append(f"Period: {period}")

    def _mom_yoy_line(obs: list[dict], label: str) -> None:
        mom = _mom_pct(obs)
        yoy = _yoy_pct(obs)
        prior_mom = _mom_pct(obs[1:]) if len(obs) >= 3 else None
        if mom is None and yoy is None:
            return
        prior_str = f" (prior MoM {prior_mom:+.2f}%)" if prior_mom is not None else ""
        mom_str = f"MoM {mom:+.2f}%" if mom is not None else "MoM —"
        yoy_str = f"YoY {yoy:+.2f}%" if yoy is not None else "YoY —"
        out.append(f"{label}: {mom_str} | {yoy_str}{prior_str}")

    _mom_yoy_line(pce_pi, "PCE price index")
    _mom_yoy_line(obs_by_id.get("PCEPILFE", []), "Core PCE (ex food/energy)")
    _mom_yoy_line(
        obs_by_id.get("IA001260M", []),
        "Supercore PCE (services ex housing & energy)",
    )

    # Spending & income — shown as MoM% on dollar levels + savings rate (already %).
    out.append("")
    out.append("=== Spending & income (MoM% on dollar levels) ===")
    for sid, label in [
        ("PI", "Personal Income"),
        ("DSPI", "Disposable Personal Income"),
        ("PCE", "Personal Consumption Expenditures (nominal)"),
        ("PCEC96", "Real PCE (chained 2017$)"),
    ]:
        obs = obs_by_id.get(sid, [])
        mom = _mom_pct(obs)
        cur = _latest(obs)
        if mom is None or cur is None:
            continue
        out.append(f"  {label:46s} ${cur:>10,.1f}B   MoM {mom:+.2f}%")

    psavert_obs = obs_by_id.get("PSAVERT", [])
    sav_cur = _latest(psavert_obs)
    sav_prv = _prior(psavert_obs)
    if sav_cur is not None:
        prior_str = f" ({sav_prv:.1f}% prior)" if sav_prv is not None else ""
        out.append(f"  {'Personal Savings Rate':46s} {sav_cur:>10.1f}%   {prior_str}")

    # Component price indexes
    out.append("")
    out.append("=== Components (price index, MoM/YoY) ===")
    for sid, label in _PCE_COMPONENTS:
        obs = obs_by_id.get(sid, [])
        mom = _mom_pct(obs)
        yoy = _yoy_pct(obs)
        if mom is None and yoy is None:
            continue
        mom_str = f"MoM {mom:+.2f}%" if mom is not None else "MoM —"
        yoy_str = f"YoY {yoy:+.2f}%" if yoy is not None else "YoY —"
        out.append(f"  {label:36s} {mom_str:14s} {yoy_str}")

    # Tape
    out.append("")
    out.append("=== Tape (intraday) ===")
    if tape_resp and tape_resp.quotes:
        for q in tape_resp.quotes:
            sym = q.get("symbol", "")
            last = q.get("last")
            chg_pct = q.get("change_percentage")
            chg = q.get("change")
            if last is None:
                continue
            if sym == "VIX":
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg:+.2f})")
            else:
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg_pct:+.2f}%)")
    else:
        out.append("  (tape unavailable)")

    # Narrative
    out.append("")
    out.append("=== BEA press release narrative ===")
    if bea_resp and bea_resp.text:
        out.append(bea_resp.text)
    else:
        out.append("(BEA Personal Income and Outlays release unavailable)")

    return "\n".join(out)


# GDP texture series — all pre-computed by BEA as quarterly % change at SAAR
# (the canonical GDP-day units), so no manual annualization needed.
_GDP_HEADLINE: list[tuple[str, str]] = [
    ("A191RL1Q225SBEA", "Real GDP"),
    ("A191RP1Q027SBEA", "Nominal GDP"),
    ("A191RI1Q225SBEA", "GDP price deflator"),
    ("PB0000031Q225SBEA", "Final sales to private domestic purchasers (real)"),
]
# Contributions to real GDP %chg (pp at SAAR). These should sum to real GDP %chg
# within rounding — that decomposition is the point.
_GDP_CONTRIBUTIONS: list[tuple[str, str]] = [
    ("DPCERY2Q224SBEA", "Personal Consumption"),
    ("A006RY2Q224SBEA", "Gross Private Domestic Investment"),
    ("A014RY2Q224SBEA", "  of which: Change in private inventories"),
    ("A019RY2Q224SBEA", "Net Exports"),
    ("A822RY2Q224SBEA", "Government Consumption & Investment"),
]
# Major aggregates and sub-components, real %chg SAAR. Mirrors the BEA Table 1
# breakdown: parents first, then notable sub-detail.
_GDP_COMPONENTS: list[tuple[str, str]] = [
    ("DPCERL1Q225SBEA", "Personal Consumption (real)"),
    ("A006RL1Q225SBEA", "Gross Private Domestic Investment (real)"),
    ("A011RL1Q225SBEA", "  Residential fixed investment"),
    ("A008RL1Q225SBEA", "  Nonresidential fixed investment"),
    ("Y033RL1Q225SBEA", "    of which: Equipment"),
    ("A020RL1Q158SBEA", "Exports (real)"),
    ("A021RL1Q158SBEA", "Imports (real)"),
    ("A822RL1Q225SBEA", "Government Consumption & Investment (real)"),
    ("A823RL1Q225SBEA", "  Federal"),
    ("A829RL1Q225SBEA", "  State & Local"),
]


async def _bea_gdp_release(
    bea_client,
) -> tuple["bea.BeaReleaseResponse | None", list[str]]:
    """Two-step BEA fetch: discover the latest GDP release URL, then fetch it.

    Returns (response, warnings). On full success, warnings is []. Each step
    that fails contributes a warning so the caller can surface it.
    """
    warnings: list[str] = []
    try:
        idx = await bea_client.get(bea.CURRENT_RELEASES, bea.EmptyRequest())
    except Exception as e:
        warnings.append(_exc_summary("BEA current-releases index", e))
        return None, warnings
    if not idx.gdp_release_path:
        warnings.append("BEA current-releases: no GDP release link found")
        return None, warnings
    try:
        resp = await bea_client.get(bea.GDP_RELEASE, bea.ReleasePathRequest(idx.gdp_release_path))
        return resp, warnings
    except Exception as e:
        warnings.append(_exc_summary(f"BEA GDP release {idx.gdp_release_path}", e))
        return None, warnings


@mcp.tool()
async def get_gdp_report_texture(ctx: Context) -> str:
    """Latest BEA Gross Domestic Product: headline + texture beneath the headline.

    Aggregates the BEA GDP press release narrative (composition commentary,
    inventory swings, trade detail, government breakdown) with FRED GDP series
    for the published headline (real GDP, nominal GDP, deflator, final sales to
    private domestic purchasers — the "core" GDP measure that strips inventories,
    government, and trade), the demand-side composition (contributions to real
    GDP growth in pp at SAAR for PCE / investment / inventories swing / net
    exports / government), and component %chg SAAR (PCE, GPDI with residential /
    nonresidential / equipment, exports, imports, government federal vs state &
    local). Includes Tradier intraday quotes for rate-sensitive tape + TIP for
    inflation expectations.

    All units are quarterly % change at SAAR (the canonical GDP-day reporting
    convention) or pp contributions to real GDP %chg.

    Returns headline + composition + components + tape + raw narrative.
    Does not interpret — surfaces the data so judgment happens in conversation
    (especially the inventory swing and net-trade contribution, which are the
    most common sources of "headline-misleads" GDP reports).

    Requires [fred] + [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    bea_client = _bea(ctx)

    # All series are quarterly. 3 obs is enough for current + 1 prior + a bit of
    # context (revisions to the prior quarter often move alongside the print).
    headline_specs = [(sid, 3) for sid, _ in _GDP_HEADLINE]
    contribution_specs = [(sid, 3) for sid, _ in _GDP_CONTRIBUTIONS]
    component_specs = [(sid, 3) for sid, _ in _GDP_COMPONENTS]
    series_specs = headline_specs + contribution_specs + component_specs

    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, lim))
        for sid, lim in series_specs
    ]
    tasks = [
        _bea_gdp_release(bea_client),
        tradier.get(t.QUOTES, t.GetQuotesRequest("TLT,IEF,SHY,SPY,XLF,TIP,VIX")),
        *fred_tasks,
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    warnings: list[str] = []
    bea_bundle = results[0]
    if isinstance(bea_bundle, BaseException):
        warnings.append(_exc_summary("BEA GDP (unexpected)", bea_bundle))
        bea_resp = None
    else:
        bea_resp, bea_warnings = bea_bundle
        warnings.extend(bea_warnings)
    tape_resp = results[1] if not isinstance(results[1], BaseException) else None
    if tape_resp is None:
        warnings.append(_exc_summary("Tradier intraday quotes", results[1]))
    obs_by_id = _collect_fred_obs(results, series_specs, 2, warnings)

    real_gdp = obs_by_id.get("A191RL1Q225SBEA", [])
    period = real_gdp[0]["date"] if real_gdp else "?"

    out: list[str] = []
    out.extend(_warnings_section(warnings))
    out.append("=== Headline (quarterly % change, annualized) ===")
    out.append(f"Period: {period}")

    def _saar_line(obs: list[dict], label: str) -> None:
        cur = _latest(obs)
        prv = _prior(obs)
        if cur is None:
            return
        prior_str = f" (prior {prv:+.2f}%)" if prv is not None else ""
        out.append(f"  {label:54s} {cur:+7.2f}%{prior_str}")

    for sid, label in _GDP_HEADLINE:
        _saar_line(obs_by_id.get(sid, []), label)

    # Composition (contributions sum to real GDP %chg)
    out.append("")
    out.append("=== Contributions to real GDP %chg (pp at SAAR) ===")
    for sid, label in _GDP_CONTRIBUTIONS:
        cur = _latest(obs_by_id.get(sid, []))
        prv = _prior(obs_by_id.get(sid, []))
        if cur is None:
            continue
        prior_str = f" (prior {prv:+.2f})" if prv is not None else ""
        out.append(f"  {label:54s} {cur:+7.2f}{prior_str}")

    # Component %chg SAAR
    out.append("")
    out.append("=== Components (real %chg SAAR) ===")
    for sid, label in _GDP_COMPONENTS:
        cur = _latest(obs_by_id.get(sid, []))
        prv = _prior(obs_by_id.get(sid, []))
        if cur is None:
            continue
        prior_str = f" (prior {prv:+.2f}%)" if prv is not None else ""
        out.append(f"  {label:54s} {cur:+7.2f}%{prior_str}")

    # Tape
    out.append("")
    out.append("=== Tape (intraday) ===")
    if tape_resp and tape_resp.quotes:
        for q in tape_resp.quotes:
            sym = q.get("symbol", "")
            last = q.get("last")
            chg_pct = q.get("change_percentage")
            chg = q.get("change")
            if last is None:
                continue
            if sym == "VIX":
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg:+.2f})")
            else:
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg_pct:+.2f}%)")
    else:
        out.append("  (tape unavailable)")

    # Narrative
    out.append("")
    out.append("=== BEA press release narrative ===")
    if bea_resp and bea_resp.text:
        out.append(bea_resp.text)
    else:
        out.append("(BEA GDP release unavailable)")

    return "\n".join(out)


async def _fed_statements(
    fed_client,
) -> tuple[
    "fed.FomcCalendarResponse | None",
    "fed.FomcStatementResponse | None",
    "fed.FomcStatementResponse | None",
    list[str],
]:
    """Two-step Fed fetch: discover latest + prior FOMC statement URLs from the
    calendar, then fetch both statements in parallel.

    Returns (calendar_resp, latest_stmt_resp, prior_stmt_resp, warnings). Any
    failed step contributes a warning so the caller can surface it.
    """
    warnings: list[str] = []
    try:
        cal = await fed_client.get(fed.FOMC_CALENDAR, fed.EmptyRequest())
    except Exception as e:
        warnings.append(_exc_summary("Fed FOMC calendar", e))
        return None, None, None, warnings
    latest_path = cal.latest()
    prior_path = cal.prior()
    if not latest_path:
        warnings.append("Fed FOMC calendar: no statement links found")
        return cal, None, None, warnings
    fetches = [fed_client.get(fed.FOMC_STATEMENT, fed.StatementPathRequest(latest_path))]
    if prior_path:
        fetches.append(fed_client.get(fed.FOMC_STATEMENT, fed.StatementPathRequest(prior_path)))
    results = await asyncio.gather(*fetches, return_exceptions=True)
    latest: fed.FomcStatementResponse | None = None
    if isinstance(results[0], BaseException):
        warnings.append(
            _exc_summary(f"Fed FOMC statement {fed.extract_meeting_date(latest_path)}", results[0])
        )
    else:
        latest = results[0]
    prior: fed.FomcStatementResponse | None = None
    if len(results) > 1:
        if isinstance(results[1], BaseException):
            warnings.append(
                _exc_summary(
                    f"Fed FOMC prior statement {fed.extract_meeting_date(prior_path)}"
                    if prior_path
                    else "Fed FOMC prior statement",
                    results[1],
                )
            )
        else:
            prior = results[1]
    return cal, latest, prior, warnings


@mcp.tool()
async def get_fomc_decision_texture(ctx: Context) -> str:
    """Latest FOMC decision: rate context + statement language + prior statement
    for comparison.

    Aggregates the Fed FOMC statement (latest meeting + the prior meeting's
    statement so language deltas are inspectable in a single tool call) with
    FRED rate series for current policy context (target range, effective fed
    funds rate, IORB, ON RRP take, balance sheet level) and Tradier intraday
    quotes for the rate-sensitive tape.

    Returns headline + policy rates + tape + latest statement + prior statement.
    Does not interpret — surfaces the data so judgment (especially the language
    diff that drives FOMC-day market reaction) happens in conversation.

    Requires [fred] + [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    fed_client = _fed(ctx)

    rate_specs = [
        ("DFEDTARU", 2),
        ("DFEDTARL", 2),
        ("DFF", 2),
        ("IORB", 2),
        ("RRPONTSYD", 2),
        ("WALCL", 30),  # need a few weeks for QT-pace context
    ]

    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, lim))
        for sid, lim in rate_specs
    ]
    results = await asyncio.gather(
        _fed_statements(fed_client),
        tradier.get(t.QUOTES, t.GetQuotesRequest("TLT,IEF,SHY,SPY,XLF,VIX")),
        *fred_tasks,
        return_exceptions=True,
    )

    warnings: list[str] = []
    fed_bundle = results[0]
    cal_resp: fed.FomcCalendarResponse | None = None
    latest_stmt: fed.FomcStatementResponse | None = None
    prior_stmt: fed.FomcStatementResponse | None = None
    if isinstance(fed_bundle, BaseException):
        warnings.append(_exc_summary("Fed FOMC fetch (unexpected)", fed_bundle))
    else:
        cal_resp, latest_stmt, prior_stmt, fed_warnings = fed_bundle
        warnings.extend(fed_warnings)
    tape_raw = results[1]
    tape_resp: t.QuotesResponse | None
    if isinstance(tape_raw, t.QuotesResponse):
        tape_resp = tape_raw
    else:
        tape_resp = None
        if isinstance(tape_raw, BaseException):
            warnings.append(_exc_summary("Tradier intraday quotes", tape_raw))
    obs_by_id = _collect_fred_obs(results, rate_specs, 2, warnings)

    upper = _latest(obs_by_id.get("DFEDTARU", []))
    lower = _latest(obs_by_id.get("DFEDTARL", []))
    dff = _latest(obs_by_id.get("DFF", []))
    iorb = _latest(obs_by_id.get("IORB", []))
    rrp = _latest(obs_by_id.get("RRPONTSYD", []))
    walcl = obs_by_id.get("WALCL", [])

    out: list[str] = []
    out.extend(_warnings_section(warnings))

    # Headline
    out.append("=== Headline ===")
    latest_path = cal_resp.latest() if cal_resp else None
    prior_path = cal_resp.prior() if cal_resp else None
    if latest_path:
        out.append(f"Latest FOMC meeting: {fed.extract_meeting_date(latest_path)}")
    if upper is not None and lower is not None:
        out.append(f"Federal Funds Target Range: {lower:.2f}% – {upper:.2f}%")
    if dff is not None:
        out.append(f"Effective Federal Funds Rate: {dff:.2f}%")

    # Policy rates
    out.append("")
    out.append("=== Policy rates ===")
    if upper is not None and lower is not None:
        out.append(f"  Federal Funds Target Range:    {lower:.2f}% – {upper:.2f}%")
    if dff is not None:
        out.append(f"  Effective Federal Funds Rate:  {dff:.2f}%")
    if iorb is not None:
        out.append(f"  IORB:                          {iorb:.2f}%")
    if rrp is not None:
        out.append(f"  ON RRP take:                   ${rrp:.2f}T")
    if walcl:
        cur_w = _latest(walcl)
        # WALCL is weekly; ~4 obs back ≈ 1 month for QT-pace context.
        prior_w = float(walcl[4]["value"]) if len(walcl) > 4 else None
        if cur_w is not None:
            line = f"  Fed balance sheet (WALCL):     ${cur_w / 1_000_000:.2f}T"
            if prior_w is not None:
                delta = (cur_w - prior_w) / 1_000_000
                line += f"  (1mo ago ${prior_w / 1_000_000:.2f}T, Δ ${delta:+.3f}T)"
            out.append(line)

    # Tape
    out.append("")
    out.append("=== Tape (intraday) ===")
    if tape_resp and tape_resp.quotes:
        for q in tape_resp.quotes:
            sym = q.get("symbol", "")
            last = q.get("last")
            chg_pct = q.get("change_percentage")
            chg = q.get("change")
            if last is None:
                continue
            if sym == "VIX":
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg:+.2f})")
            else:
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg_pct:+.2f}%)")
    else:
        out.append("  (tape unavailable)")

    # Latest statement
    out.append("")
    if latest_path and latest_stmt and latest_stmt.text:
        date_str = fed.extract_meeting_date(latest_path)
        out.append(f"=== FOMC Statement ({date_str}) ===")
        out.append(latest_stmt.text)
    else:
        out.append("=== FOMC Statement ===")
        out.append("(latest statement unavailable)")

    # Prior statement (for language diff)
    out.append("")
    if prior_path and prior_stmt and prior_stmt.text:
        date_str = fed.extract_meeting_date(prior_path)
        out.append(f"=== Prior FOMC Statement ({date_str}, for comparison) ===")
        out.append(prior_stmt.text)

    return "\n".join(out)
