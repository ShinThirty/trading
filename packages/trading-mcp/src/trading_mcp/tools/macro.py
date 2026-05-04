"""Macro and market-wide context: economic series, sector performance, market regime."""

import asyncio
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.endpoints import fmp, fred
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import kv_table

from trading_mcp.helpers import _fmp, _fred, _tradier, _year_ago

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
