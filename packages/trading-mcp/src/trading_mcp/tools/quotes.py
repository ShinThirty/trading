"""Equity and option quotes, history, intraday data, technical indicators, market clock."""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.helpers import _tradier

mcp = FastMCP("quotes-tools")


@mcp.tool()
async def get_tradier_history(
    ctx: Context,
    symbol: str,
    interval: str = "daily",
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> str:
    """Get historical OHLCV pricing data. Works for both stocks AND option contracts.

    For option contracts, pass the OCC symbol (e.g. 'AAPL260417C00260000') — use
    get_option_lookup to discover available symbols.

    symbol: ticker or OCC option symbol.
    interval: 'daily', 'weekly', or 'monthly'.
    start: start date (YYYY-MM-DD). Defaults to beginning of available data.
    end: end date (YYYY-MM-DD). Defaults to today.
    limit: max number of bars to return, keeping the most recent. Default: all bars.

    Requires [tradier] section in ~/.tradingrc.
    """
    resp = await _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, interval, start, end))
    if limit and resp.days:
        resp.days = resp.days[-limit:]
    return resp.to_output()


@mcp.tool()
async def search_symbols(ctx: Context, query: str, indexes: bool = False) -> str:
    """Search for stocks and ETFs by company name or partial symbol. Results are sorted
    by average volume (most liquid first). Useful for stock discovery.

    query: search term — company name or partial symbol (e.g. 'apple', 'semi', 'AI').
    indexes: set True to include index symbols in results.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.SEARCH, t.SearchRequest(query, indexes))).to_output()


@mcp.tool()
async def get_quote(ctx: Context, symbols: str, greeks: bool = False) -> str:
    """Get real-time quotes for stocks and/or option contracts.

    For stocks: last price, bid/ask with sizes, volume, day change/%, prev close,
    open/high/low, average volume, 52-week high/low.
    For options: last price, bid/ask with sizes, volume, day change/%, open interest,
    plus decoded strike/expiration/type from the OCC symbol.
    When greeks=True, option quotes additionally include: implied volatility (mid IV),
    delta, gamma, theta, vega, and rho.

    symbols: comma-separated ticker symbols or OCC option symbols. Can mix both in one
      call (e.g. 'AAPL,TSLA,AAPL260417C00260000'). Use get_option_lookup to find OCC
      symbols for options.
    greeks: include greeks and IV for option symbols (default False). Has no effect on
      stock symbols. Set True when evaluating option positions or comparing contracts.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(symbols, greeks))).to_output()


@mcp.tool()
async def get_timesales(
    ctx: Context,
    symbol: str,
    interval: str = "5min",
    start: str | None = None,
    end: str | None = None,
    session_filter: str = "open",
) -> str:
    """Get intraday time-and-sales tick data for a stock or option contract.
    Higher granularity than historical bars — useful for intraday analysis and charting.

    Returns: timestamp, last trade price, OHLC, and volume per interval.

    symbol: ticker or OCC option symbol (e.g. 'AAPL' or 'AAPL260417C00260000').
    interval: tick interval — '1min', '5min', '15min'. Default '5min'.
    start: start datetime (YYYY-MM-DD HH:MM). Defaults to market open today.
    end: end datetime (YYYY-MM-DD HH:MM). Defaults to now.
    session_filter: 'open' for regular hours only (default), 'all' for pre/post-market included.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (
        await _tradier(ctx).get(
            t.TIMESALES,
            t.GetTimesalesRequest(symbol, interval, start, end, session_filter),
        )
    ).to_output()


@mcp.tool()
async def get_vwap(
    ctx: Context,
    symbol: str,
    interval: str = "5min",
    session_filter: str = "open",
) -> str:
    """Compute intraday VWAP (Volume-Weighted Average Price) for a stock.

    VWAP shows where the majority of money changed hands. Institutional algorithms
    use it as a benchmark — they buy below VWAP and sell above it.

    Returns: current VWAP, price vs VWAP, time spent above/below, VWAP slope,
    and an intraday progression table.

    symbol: ticker symbol (e.g. 'SPY').
    interval: bar interval — '1min', '5min', '15min'. Default '5min'.
    session_filter: 'open' for regular hours only (default), 'all' for pre/post-market included.

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    ts_req = t.GetTimesalesRequest(symbol, interval, session_filter=session_filter)
    quote_resp, ts_resp = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.TIMESALES, ts_req),
    )

    if not ts_resp.ticks:
        return f"(no intraday data for {symbol})"

    last_price = 0.0
    if quote_resp.quotes:
        last_price = float(quote_resp.quotes[0].get("last") or 0)

    cum_vol = 0.0
    cum_tp_vol = 0.0
    above_count = 0
    below_count = 0
    vwap_values: list[float] = []
    rows: list[dict[str, str]] = []

    for tick in ts_resp.ticks:
        high = float(tick.get("high", 0))
        low = float(tick.get("low", 0))
        close = float(tick.get("close", 0))
        volume = float(tick.get("volume", 0))

        if volume == 0:
            vwap_values.append(vwap_values[-1] if vwap_values else close)
            continue

        typical_price = (high + low + close) / 3
        cum_tp_vol += typical_price * volume
        cum_vol += volume
        vwap = cum_tp_vol / cum_vol
        vwap_values.append(vwap)

        if close > vwap:
            above_count += 1
        elif close < vwap:
            below_count += 1

        rows.append(
            {
                "Time": tick.get("time", "")[-8:],
                "Close": fmt_number(close),
                "Volume": fmt_number(volume, 0),
                "VWAP": fmt_number(vwap),
                "Diff": f"{((close - vwap) / vwap) * 100:+.2f}%",
            }
        )

    if not vwap_values:
        return f"(no volume data for {symbol})"

    current_vwap = vwap_values[-1]
    total_bars = above_count + below_count

    quarter = max(1, len(vwap_values) // 4)
    early_vwap = sum(vwap_values[:quarter]) / quarter
    late_vwap = sum(vwap_values[-quarter:]) / quarter
    slope_pct = ((late_vwap - early_vwap) / early_vwap) * 100
    if slope_pct > 0.05:
        slope_label = "rising"
    elif slope_pct < -0.05:
        slope_label = "declining"
    else:
        slope_label = "flat"

    fallback_price = float(ts_resp.ticks[-1].get("close", 0))
    price_for_diff = last_price or fallback_price

    data: dict[str, str] = {
        "Price": fmt_number(price_for_diff),
        "VWAP": fmt_number(current_vwap),
    }
    diff_pct = ((price_for_diff - current_vwap) / current_vwap) * 100
    position = "above" if diff_pct > 0 else "below"
    data["Price vs VWAP"] = f"{position} by {abs(diff_pct):.2f}%"

    if total_bars > 0:
        above_pct = above_count / total_bars * 100
        data["Time Above VWAP"] = f"{above_pct:.0f}% ({above_count}/{total_bars} bars)"

    data["VWAP Slope"] = f"{slope_label} ({slope_pct:+.2f}%)"
    data["Cumulative Volume"] = fmt_number(cum_vol, 0)

    if len(rows) > 12:
        step = len(rows) // 11
        sampled = [rows[i] for i in range(0, len(rows) - 1, step)]
        sampled.append(rows[-1])
    else:
        sampled = rows

    sections = [
        f"## {symbol} VWAP ({ts_resp.ticks[0].get('time', '')[:10]})",
        "",
        kv_table(data),
        "",
        "### Intraday Progression",
        list_table(sampled),
    ]
    return "\n".join(sections)


@mcp.tool()
async def get_anchored_vwap(
    ctx: Context,
    symbol: str,
    anchor_date: str,
    end_date: str | None = None,
) -> str:
    """Compute anchored VWAP on daily bars from `anchor_date` forward.

    Acts as the institutional cost-basis level since the anchor — common anchors are
    IPO day, post-IPO peak, prior earnings, FOMC date, or a CC-write date. Price
    holding above the AVWAP = institutional buyers in green; below = underwater.

    symbol: ticker (e.g. 'CBRS', 'NVDA').
    anchor_date: ISO date the anchor starts from (inclusive), e.g. '2026-02-14'.
    end_date: optional ISO end date; defaults to today.

    Returns latest AVWAP, price vs AVWAP, and an N-bar progression.
    Requires [tradier] section in ~/.tradingrc.
    """
    resp = await _tradier(ctx).get(
        t.HISTORY, t.GetHistoryRequest(symbol, "daily", anchor_date, end_date)
    )
    bars = resp.days
    if not bars:
        return f"(no daily data for {symbol} since {anchor_date})"

    norm_bars = [
        {
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "volume": float(b.get("volume", 0) or 0),
            "date": b.get("date", ""),
        }
        for b in bars
    ]
    avwap_vals = ta.anchored_vwap(norm_bars, 0)
    if not avwap_vals or avwap_vals[-1] is None:
        return f"(no volume data for {symbol} since {anchor_date})"

    current_avwap = avwap_vals[-1]
    last_close = norm_bars[-1]["close"]
    diff_pct = (last_close - current_avwap) / current_avwap * 100
    position = "above" if diff_pct > 0 else "below"

    # Count closes above / below AVWAP since anchor
    above = sum(1 for i, v in enumerate(avwap_vals) if v is not None and norm_bars[i]["close"] > v)
    below = sum(1 for i, v in enumerate(avwap_vals) if v is not None and norm_bars[i]["close"] < v)
    total_bars = above + below

    data: dict[str, str] = {
        "Anchor Date": str(norm_bars[0]["date"]),
        "Bars Since Anchor": str(len(norm_bars)),
        "Anchor Close": fmt_number(float(norm_bars[0]["close"])),
        "Current Close": fmt_number(last_close),
        "Current AVWAP": fmt_number(current_avwap),
        "Price vs AVWAP": f"{position} by {abs(diff_pct):.2f}%",
    }
    if total_bars > 0:
        data["Closes Above AVWAP"] = f"{above / total_bars * 100:.0f}% ({above}/{total_bars})"

    rows: list[dict[str, str]] = []
    sample_count = min(12, len(norm_bars))
    if sample_count >= len(norm_bars):
        sampled_idx = list(range(len(norm_bars)))
    else:
        step = max(1, (len(norm_bars) - 1) // (sample_count - 1))
        sampled_idx = list(range(0, len(norm_bars), step))
        if sampled_idx[-1] != len(norm_bars) - 1:
            sampled_idx.append(len(norm_bars) - 1)

    for i in sampled_idx:
        v = avwap_vals[i]
        if v is None:
            continue
        close = norm_bars[i]["close"]
        rows.append(
            {
                "Date": str(norm_bars[i]["date"]),
                "Close": fmt_number(close),
                "AVWAP": fmt_number(v),
                "Diff": f"{(close - v) / v * 100:+.2f}%",
            }
        )

    sections = [
        f"## {symbol} Anchored VWAP from {norm_bars[0]['date']}",
        "",
        kv_table(data),
        "",
        "### Progression",
        list_table(rows),
    ]
    return "\n".join(sections)


@mcp.tool()
async def get_market_clock(ctx: Context) -> str:
    """Get current market status: whether the market is open, in pre-market, post-market,
    or closed, plus the time of the next state change.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.CLOCK, t.EmptyRequest())).to_output()


@mcp.tool()
async def get_technical_indicators(
    ctx: Context,
    symbol: str,
    indicators: list[str] | None = None,
    period: str = "daily",
) -> str:
    """Compute technical indicators from historical price data.

    symbol: ticker symbol (e.g. 'AAPL').
    indicators: list of indicators to compute. Default: sma, ema, rsi, macd, bbands, atr, adx, obv.
      - 'sma' — Simple Moving Average (20 and 50 period)
      - 'ema' — Exponential Moving Average (12 and 26 period)
      - 'rsi' — Relative Strength Index (14 period)
      - 'macd' — MACD line, signal, histogram (12/26/9)
      - 'bbands' — Bollinger Bands (20 period, 2 std dev) plus %B and width
      - 'atr' — Average True Range (14 period)
      - 'adx' — Average Directional Index with +DI/-DI (14 period); trend strength gauge
      - 'obv' — On-Balance Volume (cumulative signed volume) with 20-bar slope
      - 'donchian' — 20-day and 55-day Donchian channels (opt-in)
      - 'mfi' — Money Flow Index, volume-weighted RSI (14 period) (opt-in)
      - 'stochrsi' — Stochastic RSI %K / %D (14/14/3/3) (opt-in)
      - 'hv' — Historical (realized) volatility term structure 10d/30d/60d annualized (opt-in)
    period: bar interval — 'daily', 'weekly', or 'monthly'. Default 'daily'.

    Returns the latest values for each indicator plus a recent history table.
    Requires [tradier] section in ~/.tradingrc.
    """
    if indicators is None:
        indicators = ["sma", "ema", "rsi", "macd", "bbands", "atr", "adx", "obv"]

    resp = await _tradier(ctx).get(t.HISTORY, t.GetHistoryRequest(symbol, period))
    bars = resp.days
    if not bars:
        return "(no historical data)"

    closes = [float(b["close"]) for b in bars]
    latest_price = closes[-1]
    latest_date = bars[-1].get("date", "")

    sections: list[str] = [f"## {symbol} Technical Indicators ({latest_date})"]
    sections.append(f"**Price:** {latest_price:,.2f}\n")

    tail = 10

    if "rsi" in indicators:
        vals = ta.rsi(closes)
        latest = vals[-1]
        if latest is not None:
            level = "oversold" if latest < 30 else "overbought" if latest > 70 else "neutral"
            sections.append(f"**RSI(14):** {latest:.1f} ({level})")

    if "macd" in indicators:
        macd_line, signal_line, histogram = ta.macd(closes)
        m, s, h = macd_line[-1], signal_line[-1], histogram[-1]
        if m is not None and s is not None and h is not None:
            trend = "bullish" if h > 0 else "bearish"
            sections.append(
                f"**MACD(12,26,9):** line={m:.2f}, signal={s:.2f}, histogram={h:.2f} ({trend})"
            )

    if "sma" in indicators:
        sma20 = ta.sma(closes, 20)
        sma50 = ta.sma(closes, 50)
        parts = []
        if sma20[-1] is not None:
            rel = "above" if latest_price > sma20[-1] else "below"
            parts.append(f"SMA(20)={sma20[-1]:.2f} (price {rel})")
        if sma50[-1] is not None:
            rel = "above" if latest_price > sma50[-1] else "below"
            parts.append(f"SMA(50)={sma50[-1]:.2f} (price {rel})")
        if parts:
            sections.append(f"**SMA:** {', '.join(parts)}")

    if "ema" in indicators:
        ema12 = ta.ema(closes, 12)
        ema26 = ta.ema(closes, 26)
        parts = []
        if ema12[-1] is not None:
            parts.append(f"EMA(12)={ema12[-1]:.2f}")
        if ema26[-1] is not None:
            parts.append(f"EMA(26)={ema26[-1]:.2f}")
        if parts:
            sections.append(f"**EMA:** {', '.join(parts)}")

    if "bbands" in indicators:
        upper, middle, lower = ta.bollinger_bands(closes)
        if upper[-1] is not None and middle[-1] is not None and lower[-1] is not None:
            band_range = upper[-1] - lower[-1]
            width = band_range / middle[-1] * 100
            pct_b = (latest_price - lower[-1]) / band_range * 100 if band_range > 0 else 50.0
            if latest_price > upper[-1]:
                pos = "above upper band"
            elif latest_price < lower[-1]:
                pos = "below lower band"
            else:
                pos = "within bands"
            sections.append(
                f"**Bollinger(20,2):** upper={upper[-1]:.2f}, "
                f"mid={middle[-1]:.2f}, lower={lower[-1]:.2f} "
                f"(width={width:.1f}%, %B={pct_b:.0f}, {pos})"
            )

    if "atr" in indicators:
        atr_vals = ta.atr(bars)
        if atr_vals[-1] is not None:
            atr_pct = atr_vals[-1] / latest_price * 100
            sections.append(f"**ATR(14):** {atr_vals[-1]:.2f} ({atr_pct:.1f}% of price)")

    if "adx" in indicators:
        adx_vals, plus_di, minus_di = ta.adx(bars)
        a, p, m = adx_vals[-1], plus_di[-1], minus_di[-1]
        if a is not None and p is not None and m is not None:
            if a < 20:
                zone = "ranging"
            elif a < 25:
                zone = "transitional"
            elif a < 40:
                zone = "trending"
            else:
                zone = "strong trend"
            bias = "+DI > -DI (up bias)" if p > m else "-DI > +DI (down bias)"
            sections.append(f"**ADX(14):** {a:.1f} ({zone}); +DI={p:.1f}, -DI={m:.1f} ({bias})")

    if "obv" in indicators:
        obv_vals = ta.obv(bars)
        if obv_vals[-1] is not None and len(obv_vals) >= 21 and obv_vals[-21] is not None:
            cur = obv_vals[-1]
            prior = obv_vals[-21]
            price_prior = closes[-21]
            obv_chg = cur - prior
            price_chg_pct = (latest_price - price_prior) / price_prior * 100
            if obv_chg > 0 and price_chg_pct > 0:
                tag = "confirming (both up)"
            elif obv_chg < 0 and price_chg_pct < 0:
                tag = "confirming (both down)"
            elif price_chg_pct > 0 and obv_chg <= 0:
                tag = "bearish divergence (price up, OBV flat/down)"
            elif price_chg_pct < 0 and obv_chg >= 0:
                tag = "bullish divergence (price down, OBV up)"
            else:
                tag = "mixed"
            sections.append(
                f"**OBV:** 20d Δ={obv_chg:+,.0f} vs price {price_chg_pct:+.1f}% — {tag}"
            )

    if "donchian" in indicators:
        u20, _, l20 = ta.donchian(bars, 20)
        u55, _, l55 = ta.donchian(bars, 55)
        parts: list[str] = []
        if u20[-1] is not None and l20[-1] is not None:
            parts.append(
                f"20d high={u20[-1]:.2f} ({(latest_price - u20[-1]) / u20[-1] * 100:+.1f}%), "
                f"low={l20[-1]:.2f} ({(latest_price - l20[-1]) / l20[-1] * 100:+.1f}%)"
            )
        if u55[-1] is not None and l55[-1] is not None:
            parts.append(
                f"55d high={u55[-1]:.2f} ({(latest_price - u55[-1]) / u55[-1] * 100:+.1f}%), "
                f"low={l55[-1]:.2f} ({(latest_price - l55[-1]) / l55[-1] * 100:+.1f}%)"
            )
        if parts:
            sections.append("**Donchian:** " + "; ".join(parts))

    if "mfi" in indicators:
        mfi_vals = ta.mfi(bars)
        if mfi_vals[-1] is not None:
            v = mfi_vals[-1]
            zone = "oversold" if v < 20 else "overbought" if v > 80 else "neutral"
            sections.append(f"**MFI(14):** {v:.1f} ({zone})")

    if "stochrsi" in indicators:
        k_vals, d_vals = ta.stochastic_rsi(closes)
        k, d = k_vals[-1], d_vals[-1]
        if k is not None and d is not None:
            zone = "oversold" if k < 20 else "overbought" if k > 80 else "neutral"
            cross = "bull cross" if k > d else "bear cross" if k < d else "flat"
            sections.append(f"**StochRSI(14,14,3,3):** %K={k:.1f}, %D={d:.1f} ({zone}, {cross})")

    if "hv" in indicators:
        hv10 = ta.historical_volatility(closes, 10)
        hv30 = ta.historical_volatility(closes, 30)
        hv60 = ta.historical_volatility(closes, 60)
        parts2: list[str] = []
        if hv10[-1] is not None:
            parts2.append(f"HV10={hv10[-1]:.1f}%")
        if hv30[-1] is not None:
            parts2.append(f"HV30={hv30[-1]:.1f}%")
        if hv60[-1] is not None:
            parts2.append(f"HV60={hv60[-1]:.1f}%")
        if parts2:
            shape = ""
            if hv10[-1] is not None and hv30[-1] is not None and hv60[-1] is not None:
                if hv10[-1] > hv30[-1] > hv60[-1]:
                    shape = " — realized vol rising"
                elif hv10[-1] < hv30[-1] < hv60[-1]:
                    shape = " — realized vol cooling"
            sections.append("**HV term structure:** " + ", ".join(parts2) + shape)

    sections.append("\n### Recent Values")

    rows = []
    start = max(0, len(bars) - tail)
    rsi_vals = ta.rsi(closes) if "rsi" in indicators else []
    sma20_vals = ta.sma(closes, 20) if "sma" in indicators else []
    atr_vals_full = ta.atr(bars) if "atr" in indicators else []

    for i in range(start, len(bars)):
        row: dict[str, str] = {
            "Date": bars[i].get("date", ""),
            "Close": fmt_number(closes[i]),
        }
        if rsi_vals:
            row["RSI"] = fmt_number(rsi_vals[i], 1) if rsi_vals[i] is not None else ""
        if sma20_vals:
            row["SMA20"] = fmt_number(sma20_vals[i]) if sma20_vals[i] is not None else ""
        if atr_vals_full:
            row["ATR"] = fmt_number(atr_vals_full[i]) if atr_vals_full[i] is not None else ""
        rows.append(row)

    sections.append(list_table(rows))
    return "\n".join(sections)
