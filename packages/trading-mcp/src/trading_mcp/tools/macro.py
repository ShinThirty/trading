"""Macro and market-wide context: economic series, sector performance, market regime."""

import asyncio
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.endpoints import bls, fmp, fred
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import kv_table

from trading_mcp.helpers import _bls, _fmp, _fred, _tradier, _year_ago

mcp = FastMCP("macro-tools")

HISTORY_SYMBOLS = ["SPY", "SMH", "IWM", *regime.SECTOR_ETFS]


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

    def _ok(i: int):
        return results[i] if not isinstance(results[i], BaseException) else None

    bls_resp = _ok(0)
    tape_resp = _ok(1)
    obs_by_id: dict[str, list[dict]] = {}
    for i, (sid, _) in enumerate(series_specs, start=2):
        r = _ok(i)
        if r is not None:
            obs_by_id[sid] = r.observations or []

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

    def _ok(i: int):
        return results[i] if not isinstance(results[i], BaseException) else None

    bls_resp = _ok(0)
    tape_resp = _ok(1)
    obs_by_id: dict[str, list[dict]] = {}
    for i, (sid, _) in enumerate(series_specs, start=2):
        r = _ok(i)
        if r is not None:
            obs_by_id[sid] = r.observations or []

    headline = obs_by_id.get("CPIAUCSL", [])
    core = obs_by_id.get("CPILFESL", [])
    period = headline[0]["date"] if headline else "?"

    out: list[str] = []
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

    Requires [fred] and [tradier] sections in ~/.tradingrc.
    TastyTrade is optional enrichment.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    tt_client = ctx.lifespan_context.get("tastytrade")

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
    if spy_closes:
        price = spy_closes[-1]
        rsi_vals = ta.rsi(spy_closes)
        sma50_vals = ta.sma(spy_closes, 50)
        sma200_vals = ta.sma(spy_closes, 200)
        label, detail = regime.classify_trend(price, rsi_vals[-1], sma50_vals[-1], sma200_vals[-1])
        labels["trend"] = label
        data["Trend"] = f"{label} ({detail})"

    iwm_closes = closes.get("IWM", [])
    xlu_closes = closes.get("XLU", [])
    xly_closes = closes.get("XLY", [])
    if spy_closes and iwm_closes and xlu_closes and xly_closes:
        label, detail = regime.classify_breadth(
            spy_closes, iwm_closes, spy_volumes, xlu_closes, xly_closes
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

    return f"## Market Regime\n\n**Verdict: {verdict}**  \n*Why: {evidence}*\n\n{kv_table(data)}"
