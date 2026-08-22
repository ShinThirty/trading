"""Crypto quotes/history and the BTC entry-signal aggregator."""

import asyncio
from datetime import date
from typing import Any

import httpx
from fastmcp import Context, FastMCP
from trading_clients import btc_regime as btc
from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.endpoints import fred
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    CRYPTO_BARS,
    CRYPTO_SNAPSHOT,
    CryptoBarsRequest,
    CryptoSnapshotRequest,
)
from trading_clients.table_helpers import kv_table, to_float

from trading_mcp.helpers import _fred, _tradier, _webull, _year_ago

mcp = FastMCP("crypto-tools")

_FNG_URL = "https://api.alternative.me/fng/"


async def _fetch_fear_greed() -> int | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_FNG_URL, params={"limit": "1", "format": "json"})
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                return int(data[0]["value"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass
    return None


@mcp.tool()
async def get_crypto_quote(ctx: Context, symbols: str = "BTCUSD") -> str:
    """Get real-time crypto price snapshot from Webull.

    symbols: comma-separated crypto symbols (e.g. 'BTCUSD', 'BTCUSD,ETHUSD').
      Default: BTCUSD.

    Returns current price, change, bid/ask, and day range.
    Requires [webull] section in ~/.tradingrc.
    """
    client = _webull(ctx)
    resp = await client.get(CRYPTO_SNAPSHOT, CryptoSnapshotRequest(symbols))
    return resp.to_output()


@mcp.tool()
async def get_crypto_history(
    ctx: Context,
    symbol: str = "BTCUSD",
    interval: str = "D",
    count: int = 200,
) -> str:
    """Get historical OHLCV bars for a cryptocurrency from Webull.

    symbol: crypto symbol (e.g. 'BTCUSD', 'ETHUSD'). Default: BTCUSD.
    interval: bar interval — 'D' (daily), 'W' (weekly), 'M' (monthly),
      '1' (1min), '5' (5min), '30' (30min), '60' (60min). Default: D.
    count: number of bars to return (max 250). Default: 200.

    Returns OHLCV table sorted oldest to newest.
    Requires [webull] section in ~/.tradingrc.
    """
    client = _webull(ctx)
    resp = await client.get(CRYPTO_BARS, CryptoBarsRequest(symbol, timespan=interval, count=count))
    return resp.to_output()


@mcp.tool()
async def get_btc_entry_signals(ctx: Context) -> str:
    """Get Bitcoin entry signals combining macro indicators and BTC price
    technicals into a single scorecard.

    Macro signals (from FRED):
    - Halving Cycle: position in Bitcoin's ~4-year supply cycle
    - Monetary Policy: Fed funds rate direction (easing/tightening/holding)
    - Liquidity: M2 money supply YoY growth + 3mo acceleration
    - Dollar: DXY 20d/60d trend (weak dollar = bullish BTC)
    - Real Rates: 10Y yield minus CPI (negative = bullish BTC)
    - Risk Appetite: VIX level
    - Sentiment: Crypto Fear & Greed Index (contrarian indicator)

    Price technicals (from Webull crypto bars):
    - BTC price, drawdown from the all-time high (monthly bars, ~20y of history)
    - RSI(14), SMA(50), SMA(200) (250 daily bars)

    Correlation regime (from Webull + Tradier):
    - BTC vs QQQ (risk-on) and BTC vs GLD (store-of-value) 30-day correlation
    - Composite: overall macro favorability score

    Requires [fred], [webull], and [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    webull = _webull(ctx)
    tradier = _tradier(ctx)
    start_date = _year_ago(date.today()).isoformat()

    tasks: list[Any] = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", 2)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("WM2NS", 60)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DTWEXBGS", 80)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS10", 1)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("CPIAUCSL", 13)),
        tradier.get(t.QUOTES, t.GetQuotesRequest("VIX")),
        webull.get(CRYPTO_BARS, CryptoBarsRequest("BTCUSD", timespan="D", count=250)),
        webull.get(CRYPTO_SNAPSHOT, CryptoSnapshotRequest("BTCUSD")),
        _fetch_fear_greed(),
        tradier.get(t.HISTORY, t.GetHistoryRequest("QQQ", "daily", start=start_date)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("GLD", "daily", start=start_date)),
        webull.get(CRYPTO_BARS, CryptoBarsRequest("BTCUSD", timespan="M", count=250)),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    ff_resp = results[0] if not isinstance(results[0], BaseException) else None
    m2_resp = results[1] if not isinstance(results[1], BaseException) else None
    dxy_resp = results[2] if not isinstance(results[2], BaseException) else None
    dgs10_resp = results[3] if not isinstance(results[3], BaseException) else None
    cpi_resp = results[4] if not isinstance(results[4], BaseException) else None
    vix_quotes_resp = results[5] if not isinstance(results[5], BaseException) else None
    bars_resp = results[6] if not isinstance(results[6], BaseException) else None
    snap_resp = results[7] if not isinstance(results[7], BaseException) else None
    fng_val = results[8] if not isinstance(results[8], BaseException) else None
    qqq_resp = results[9] if not isinstance(results[9], BaseException) else None
    gld_resp = results[10] if not isinstance(results[10], BaseException) else None
    monthly_resp = results[11] if not isinstance(results[11], BaseException) else None

    data: dict[str, str | None] = {}
    labels: dict[str, str] = {}

    btc_price = None
    if snap_resp and snap_resp.snapshots:
        s = snap_resp.snapshots[0]
        btc_price = to_float(s.get("price"))
        change_ratio = to_float(s.get("change_ratio"))
        if btc_price:
            price_str = f"${btc_price:,.0f}"
            if change_ratio is not None:
                price_str += f" ({change_ratio * 100:+.2f}%)"
            data["BTC Price"] = price_str

    bars = bars_resp.bars if bars_resp else []
    closes = [float(b["close"]) for b in bars if b.get("close")] if bars else []
    ath: float | None = None

    monthly_highs = (
        [float(b["high"]) for b in monthly_resp.bars if b.get("high")] if monthly_resp else []
    )

    if closes:
        current = btc_price or closes[-1]
        # See btc.all_time_high: the ATH must come from monthly bars, never from
        # the 250-bar daily window, which only reaches back ~8 months.
        ath = btc.all_time_high(monthly_highs, closes, current)
        drawdown = (current - ath) / ath * 100 if ath and ath > 0 else 0
        if ath:
            data["ATH Drawdown"] = f"{drawdown:+.1f}% (ATH ${ath:,.0f})"

        rsi_vals = ta.rsi(closes)
        rsi_val = rsi_vals[-1] if rsi_vals else None
        if rsi_val is not None:
            level = "oversold" if rsi_val < 30 else "overbought" if rsi_val > 70 else "neutral"
            data["RSI(14)"] = f"{rsi_val:.1f} ({level})"

        sma50_vals = ta.sma(closes, 50)
        sma50 = sma50_vals[-1]
        if sma50 is not None and current:
            rel = "above" if current > sma50 else "below"
            data["SMA(50)"] = f"${sma50:,.0f} (price {rel})"

        sma200_vals = ta.sma(closes, 200)
        sma200 = sma200_vals[-1]
        if sma200 is not None and current:
            rel = "above" if current > sma200 else "below"
            data["SMA(200)"] = f"${sma200:,.0f} (price {rel})"

    btc_by_date: dict[str, float] = {}
    for b in bars:
        t_str = b.get("time", "")
        close = to_float(b.get("close"))
        if t_str and close:
            btc_by_date[t_str[:10]] = close

    qqq_by_date: dict[str, float] = {}
    if qqq_resp and qqq_resp.days:
        for d in qqq_resp.days:
            qqq_by_date[d.get("date", "")] = float(d["close"])

    gld_by_date: dict[str, float] = {}
    if gld_resp and gld_resp.days:
        for d in gld_resp.days:
            gld_by_date[d.get("date", "")] = float(d["close"])

    if btc_by_date and qqq_by_date and gld_by_date:
        corr_label, corr_detail = btc.classify_correlation(btc_by_date, qqq_by_date, gld_by_date)
        data["Correlation"] = f"{corr_label} — {corr_detail}"

    label, detail = btc.classify_halving_cycle()
    data["Halving Cycle"] = f"{label} — {detail}"
    labels["Halving Cycle"] = label

    ff_obs = ff_resp.observations if ff_resp else []
    ff_val, _ = regime.parse_fred_value(ff_obs)
    prev_ff_val, _ = regime.parse_fred_value(ff_obs[1:] if len(ff_obs) > 1 else [])
    label, detail = btc.classify_monetary_policy(ff_val, prev_ff_val)
    data["Monetary Policy"] = f"{label} — {detail}"
    labels["Monetary Policy"] = label

    m2_obs = m2_resp.observations if m2_resp else []
    m2_values: list[tuple[str, float]] = []
    for obs in m2_obs:
        v = obs.get("value", ".")
        if v != ".":
            try:
                m2_values.append((obs.get("date", ""), float(v)))
            except (ValueError, TypeError):
                pass
    label, detail = btc.classify_liquidity(m2_values)
    data["Liquidity"] = f"{label} — {detail}"
    labels["Liquidity"] = label

    dxy_obs = dxy_resp.observations if dxy_resp else []
    dxy_values: list[tuple[str, float]] = []
    for obs in dxy_obs:
        v = obs.get("value", ".")
        if v != ".":
            try:
                dxy_values.append((obs.get("date", ""), float(v)))
            except (ValueError, TypeError):
                pass
    label, detail = btc.classify_dollar(dxy_values)
    data["Dollar"] = f"{label} — {detail}"
    labels["Dollar"] = label

    dgs10_val, _ = regime.parse_fred_value(dgs10_resp.observations if dgs10_resp else [])
    cpi_obs = cpi_resp.observations if cpi_resp else []
    cpi_yoy = None
    if len(cpi_obs) >= 13:
        try:
            current_cpi = float(cpi_obs[0].get("value", "."))
            year_ago_cpi = float(cpi_obs[12].get("value", "."))
            if year_ago_cpi > 0:
                cpi_yoy = (current_cpi - year_ago_cpi) / year_ago_cpi * 100
        except (ValueError, TypeError):
            pass
    label, detail = btc.classify_real_rates(dgs10_val, cpi_yoy)
    data["Real Rates"] = f"{label} — {detail}"
    labels["Real Rates"] = label

    vix_val = None
    if vix_quotes_resp and vix_quotes_resp.quotes:
        vix_val = vix_quotes_resp.quotes[0].get("last")
    label, detail = btc.classify_risk_appetite(vix_val)
    data["Risk Appetite"] = f"{label} — {detail}"
    labels["Risk Appetite"] = label

    label, detail = btc.classify_fear_greed(fng_val)
    data["Sentiment"] = f"{label} — {detail}"
    labels["Sentiment"] = label

    data["Composite"] = btc.macro_scorecard(labels)

    if btc_price and ath:
        data["DCA Sizing"] = btc.dca_sizing(btc_price, ath)

    return f"## BTC Entry Signals\n\n{kv_table(data)}"
