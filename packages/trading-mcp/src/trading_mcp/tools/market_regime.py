import asyncio
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.endpoints import fmp, fred
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import kv_table

from trading_mcp.helpers import _fred, _tradier, _year_ago

mcp = FastMCP("market-regime-tools")


@mcp.tool()
async def get_market_regime(ctx: Context) -> str:
    """Get current market regime classification across volatility, trend,
    macro, and sector dimensions.

    Aggregates Tradier (live VIX/VIX3M quotes, SPY technicals),
    FRED (yield curve, fed funds), FMP (sector performance), and
    TastyTrade (IV enrichment) into simple regime labels.

    Returns regime labels with supporting data:
    - Volatility: Low / Normal / Elevated / Crisis (VIX + term structure)
    - Trend: Uptrend / Sideways / Downtrend (SPY RSI + SMA 50/200)
    - Macro: Steep / Flat / Inverted yield curve (10Y-2Y + Fed funds)
    - Sectors: Risk-On / Rotation / Risk-Off (high-beta vs defensive)

    Requires [fred] and [tradier] sections in ~/.tradingrc.
    FMP and TastyTrade are optional enrichments.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    fmp_client = ctx.lifespan_context.get("fmp")
    tt_client = ctx.lifespan_context.get("tastytrade")

    tasks = [
        tradier.get(t.QUOTES, t.GetQuotesRequest("VIX,VIX3M")),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("T10Y2Y", 130)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 2)),
        tradier.get(
            t.HISTORY,
            t.GetHistoryRequest("SPY", "daily", start=_year_ago(date.today()).isoformat()),
        ),
        tradier.get(
            t.HISTORY,
            t.GetHistoryRequest("SMH", "daily", start=_year_ago(date.today()).isoformat()),
        ),
    ]

    if fmp_client:
        tasks.append(
            fmp_client.get(
                fmp.SECTOR_PERFORMANCE,
                fmp.SectorPerformanceRequest(date.today().isoformat()),
            )
        )
    if tt_client:
        tasks.append(tt_client.get(tt.MARKET_METRICS, tt.MarketMetricsRequest("SPY")))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    vix_quotes_resp = results[0] if not isinstance(results[0], BaseException) else None
    spread_resp = results[1] if not isinstance(results[1], BaseException) else None
    ff_resp = results[2] if not isinstance(results[2], BaseException) else None
    spy_resp = results[3] if not isinstance(results[3], BaseException) else None
    smh_resp = results[4] if not isinstance(results[4], BaseException) else None

    idx = 5
    sector_resp = None
    if fmp_client:
        sector_resp = results[idx] if not isinstance(results[idx], BaseException) else None
        idx += 1
    tt_resp = None
    if tt_client:
        tt_resp = results[idx] if not isinstance(results[idx], BaseException) else None

    data: dict[str, str | None] = {}

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
        data["Volatility"] = f"{label} ({detail})"

    if spy_resp and spy_resp.days:
        closes = [float(b["close"]) for b in spy_resp.days]
        price = closes[-1]
        rsi_vals = ta.rsi(closes)
        sma50_vals = ta.sma(closes, 50)
        sma200_vals = ta.sma(closes, 200)
        label, detail = regime.classify_trend(price, rsi_vals[-1], sma50_vals[-1], sma200_vals[-1])
        data["Trend"] = f"{label} ({detail})"

    spread_observations = spread_resp.observations if spread_resp else []
    spread_val, _ = regime.parse_fred_value(spread_observations)
    ff_observations = ff_resp.observations if ff_resp else []
    ff_val, _ = regime.parse_fred_value(ff_observations)
    prev_ff_obs = ff_observations[1:] if len(ff_observations) > 1 else []
    prev_ff_val, _ = regime.parse_fred_value(prev_ff_obs)
    label, detail = regime.classify_macro(spread_val, ff_val, prev_ff_val)
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
        data["\u26a0 Macro"] = trap_warning

    if sector_resp and sector_resp.sectors:
        label, detail = regime.classify_sectors(sector_resp.sectors)
        data["Sectors"] = f"{label} ({detail})"

    if smh_resp and smh_resp.days and spy_resp and spy_resp.days:
        smh_closes = [float(b["close"]) for b in smh_resp.days]
        spy_closes_all = [float(b["close"]) for b in spy_resp.days]
        semi_warning = regime.detect_semi_divergence(smh_closes, spy_closes_all)
        if semi_warning:
            data["\u26a0 Sectors"] = semi_warning

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

    return f"## Market Regime\n\n{kv_table(data)}"
