import asyncio
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.endpoints import fred
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import kv_table

from trading_mcp.helpers import _fred, _tradier, _year_ago

mcp = FastMCP("market-regime-tools")

HISTORY_SYMBOLS = ["SPY", "SMH", "IWM", *regime.SECTOR_ETFS]


@mcp.tool()
async def get_market_regime(ctx: Context) -> str:
    """Get current market regime classification across volatility, trend,
    breadth, macro, and sector dimensions.

    Aggregates Tradier (live VIX/VIX3M quotes, SPY/IWM technicals,
    11 SPDR sector ETF histories), FRED (yield curve, fed funds), and
    TastyTrade (IV enrichment) into simple regime labels.

    Returns regime labels with supporting data:
    - Volatility: Low / Normal / Elevated / Crisis (VIX + term structure)
    - Trend: Uptrend / Sideways / Downtrend (SPY RSI + SMA 50/200)
    - Breadth: Broadening / Healthy / Mixed / Narrowing (SPY/IWM, XLU/XLY, volume)
    - Macro: Steep / Flat / Inverted yield curve (10Y-2Y + Fed funds)
    - Sectors: Risk-On / Rotation / Risk-Off (multi-timeframe ETF rotation
      with 30/60/90d returns, leadership ranking, and momentum shifts)

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
    ]

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

    closes: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    for i, sym in enumerate(HISTORY_SYMBOLS):
        resp = _ok(3 + i)
        if resp and resp.days:
            closes[sym] = [float(b["close"]) for b in resp.days]
            volumes[sym] = [float(b["volume"]) for b in resp.days]

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

    spy_closes = closes.get("SPY", [])
    spy_volumes = volumes.get("SPY", [])
    if spy_closes:
        price = spy_closes[-1]
        rsi_vals = ta.rsi(spy_closes)
        sma50_vals = ta.sma(spy_closes, 50)
        sma200_vals = ta.sma(spy_closes, 200)
        label, detail = regime.classify_trend(price, rsi_vals[-1], sma50_vals[-1], sma200_vals[-1])
        data["Trend"] = f"{label} ({detail})"

    iwm_closes = closes.get("IWM", [])
    xlu_closes = closes.get("XLU", [])
    xly_closes = closes.get("XLY", [])
    if spy_closes and iwm_closes and xlu_closes and xly_closes:
        label, detail = regime.classify_breadth(
            spy_closes, iwm_closes, spy_volumes, xlu_closes, xly_closes
        )
        data["Breadth"] = f"{label} ({detail})"

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
        data["⚠ Macro"] = trap_warning

    sector_closes = {sym: closes[sym] for sym in regime.SECTOR_ETFS if sym in closes}
    if len(sector_closes) >= 6:
        label, detail = regime.classify_sector_rotation(sector_closes)
        data["Sectors"] = f"{label} ({detail})"

    smh_closes = closes.get("SMH", [])
    if smh_closes and spy_closes:
        semi_warning = regime.detect_semi_divergence(smh_closes, spy_closes)
        if semi_warning:
            data["⚠ Sectors"] = semi_warning

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

    return f"## Market Regime\n\n{kv_table(data)}"
