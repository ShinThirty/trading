"""Equity and option quotes, history, intraday data, technical indicators, market clock,
plus Yahoo-sourced foreign-market quotes, FX rates, and ADR parity."""

import asyncio
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients import indicators as ta
from trading_clients.adr import compute_adr_parity
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_large, fmt_number, kv_table, list_table

from trading_mcp.helpers import _HV_EFF_FLOOR, _HV_EFF_WINDOW, _hv_effective_n, _tradier
from trading_mcp.yfinance_helper import _yfc

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
async def get_global_quote(ctx: Context, symbols: str) -> str:
    """Get quotes for foreign-listed tickers via Yahoo Finance — the complement to
    get_quote (US markets, Tradier) and get_cn_quote (China A-shares) for markets
    neither covers: Korea, Japan, Taiwan, Europe, etc.

    Prices are the latest daily bar: ~15-20 min delayed while the home market
    trades, the official close after it closes. Output includes the bar date —
    check it when the home market's holiday calendar differs from the US one.

    symbols: comma-separated Yahoo symbols with exchange suffix
      (e.g. '000660.KS' Korea, '7203.T' Tokyo, '2330.TW' Taiwan, 'ASML.AS' Amsterdam).
    """
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    if not syms:
        return "(no symbols)"
    results = await asyncio.gather(*(_yfc.global_quote(s) for s in syms))
    rows: list[dict[str, str]] = []
    for sym, q in zip(syms, results):
        if not q:
            rows.append({"Symbol": sym, "Close": "(no data)"})
            continue
        prev = q.get("prev_close")
        chg = f"{(q['close'] - prev) / prev * 100:+.2f}%" if prev else ""
        rows.append(
            {
                "Symbol": sym,
                "Close": fmt_number(q["close"]),
                "Chg%": chg,
                "Prev Close": fmt_number(prev),
                "Day Range": f"{fmt_number(q['low'])}-{fmt_number(q['high'])}",
                "Volume": fmt_large(q["volume"]),
                "Currency": q.get("currency", ""),
                "Exchange": q.get("exchange", ""),
                "Bar Date": q["date"],
            }
        )
    return list_table(rows)


@mcp.tool()
async def get_fx_rate(ctx: Context, pair: str) -> str:
    """Get a live FX rate via Yahoo Finance. Near-real-time (FX trades ~24h on
    weekdays), unlike FRED's daily H.10 series (e.g. DEXKOUS) which publish with
    a lag — use this for live conversions, FRED for history.

    pair: 6-letter pair like 'USDKRW' or 'EURUSD' (rate = quote-currency units per
      1 unit of base currency), or a bare 3-letter code like 'KRW' (read as USD<CCY>).
    """
    p = pair.strip().upper()
    if len(p) == 3:
        p = "USD" + p
    if len(p) != 6 or not p.isalpha():
        raise ValueError(f"pair must be a 3- or 6-letter currency code, got {pair!r}")
    fx = await _yfc.fx_rate(p)
    if not fx:
        return f"(no FX data for {p[:3]}/{p[3:]})"
    rate = fx["rate"]
    return kv_table(
        {
            "Pair": f"{p[:3]}/{p[3:]}",
            "Rate": fmt_number(rate, 4),
            "Inverse": fmt_number(1 / rate, 6),
            "As Of": fx["asof"],
        }
    )


@mcp.tool()
async def get_adr_premium(
    ctx: Context,
    adr_symbol: str,
    ordinary_symbol: str,
    ordinary_shares_per_adr: float,
    home_currency: str,
) -> str:
    """Compute a US-listed ADR/ADS premium or discount vs FX-adjusted home-market
    parity: fair value = ordinary close x ordinary_shares_per_adr / (home currency
    per USD), compared against the live US quote. Use for cross-listed names where
    the parity gap is a standing gauge (e.g. SKHY vs Seoul 000660).

    adr_symbol: US ADR/ADS ticker (e.g. 'SKHY', 'TSM').
    ordinary_symbol: home-market Yahoo symbol (e.g. '000660.KS', '2330.TW').
    ordinary_shares_per_adr: deposit ratio as ordinary shares per one ADR — set in
      the deposit agreement, NOT standardized, and amendable by the issuer
      (SKHY: 0.1, i.e. 1 ADS = 1/10 common; TSM: 5.0). Verify against the
      prospectus/F-6 before first use; a wrong ratio is a silent 10-100x error.
    home_currency: ISO code the ordinary line trades in (e.g. 'KRW', 'TWD') —
      cross-checked against Yahoo's reported trading currency.

    Requires [tradier] section in ~/.tradingrc.
    """
    ccy = home_currency.strip().upper()
    quote_resp, ordinary, fx = await asyncio.gather(
        _tradier(ctx).get(t.QUOTES, t.GetQuotesRequest(adr_symbol, greeks=False)),
        _yfc.global_quote(ordinary_symbol),
        _yfc.fx_rate("USD" + ccy),
    )
    if not quote_resp.quotes:
        return f"(no US quote for {adr_symbol})"
    adr_last = float(quote_resp.quotes[0].get("last") or 0)
    if adr_last <= 0:
        return f"(no last price for {adr_symbol})"
    if not ordinary:
        return f"(no Yahoo data for {ordinary_symbol})"
    if not fx:
        return f"(no FX data for USD/{ccy})"

    reported_ccy = str(ordinary.get("currency") or "")
    if reported_ccy and reported_ccy.upper() != ccy:
        raise ValueError(
            f"{ordinary_symbol} trades in {reported_ccy}, not {ccy} — fix home_currency "
            "(note: 'GBp' is pence — London lines need the /100 handled explicitly)"
        )

    parity = compute_adr_parity(
        adr_symbol=adr_symbol.upper(),
        ordinary_symbol=ordinary_symbol,
        adr_price=adr_last,
        ordinary_price=ordinary["close"],
        ordinary_shares_per_adr=ordinary_shares_per_adr,
        fx_rate=fx["rate"],
        ordinary_bar_date=ordinary["date"],
    )
    out = parity.to_output()
    bar_age = (date.today() - date.fromisoformat(ordinary["date"])).days
    if bar_age > 4:
        out += (
            f"\n\n**WARNING:** ordinary close is {bar_age} days old (home-market holiday "
            "or stale feed) — the premium may be misleading."
        )
    return out


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


# Indicators whose reading is built on short-window return dispersion, and so inherit
# whatever single bar dominates it (see _hv_effective_n in helpers for the calibration).
# `hv` is opt-in, so gating the diagnostic on it alone would hide it from every default
# call — rsi and bbands are both in the default set.
_VARIANCE_CONSUMERS = frozenset({"hv", "bbands", "stochrsi", "rsi"})


def _concentration_warning(
    bars: list[dict], closes: list[float], indicators: list[str]
) -> list[str]:
    """Report how many bars the short-window variance reading actually rests on."""
    if not _VARIANCE_CONSUMERS.intersection(indicators):
        return []
    measured = _hv_effective_n(closes)
    if measured is None:
        return []
    eff_n, top_share, bar_idx = measured
    when = str(bars[bar_idx].get("date", "?")) if bar_idx < len(bars) else "?"
    if eff_n >= _HV_EFF_FLOOR:
        return [
            f"Short-window variance rests on ~{eff_n:.1f} of {_HV_EFF_WINDOW} bars "
            f"(largest, {when}, is {top_share:.0f}% of it; ~4/10 is typical).\n"
        ]
    return [
        f"⚠ **Short-window variance is ~{eff_n:.1f} of {_HV_EFF_WINDOW} bars** — {when} "
        f"alone owns {top_share:.0f}% of it. Readings built on it (HV10, Bollinger "
        "%B/width, StochRSI, RSI) describe that bar more than the tape; a gap can invert "
        "%B and StochRSI outright. Prefer `get_variance_risk_premium` — its HAR "
        "forecast blends daily/weekly/monthly precisely to survive this — and anchor "
        "OBV past the bar via `obv_anchor_date`.\n",
    ]


@mcp.tool()
async def get_technical_indicators(
    ctx: Context,
    symbol: str,
    indicators: list[str] | None = None,
    period: str = "daily",
    obv_anchor_date: str | None = None,
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
    obv_anchor_date: optional ISO date (inclusive) to anchor the OBV accumulation,
        e.g. '2026-08-06'. Affects the 'obv' line only — every other indicator is a
        fixed-lookback window. Default (unset) is the trailing 20-bar slope.

        Anchor at the first session after a gap event when the question is "who has
        been accumulating since". The default 20-bar window spans roughly a month, so
        an earnings gap inside it contributes one bar at several times normal volume
        and dominates the sum — the reported divergence is then the gap itself, not
        the flow after it. Anchoring drops the gap bar and starts the count at zero.

    Returns the latest values for each indicator plus a recent history table.

    When any short-window-variance indicator is requested (rsi, bbands, stochrsi, hv),
    the output leads with how many bars that variance window effectively rests on —
    inverse-Herfindahl effective N. A 10-bar window carries a median 4.1 of its 10
    bars, so treat HV10, %B and StochRSI as indicative rather than measured, and treat
    a reading below ~2.5 as one bar wearing a trend's clothing.

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
    sections.extend(_concentration_warning(bars, closes, indicators))

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
        # Anchored: baseline is the anchor bar (OBV resets to 0 there). Otherwise the
        # legacy trailing 20-bar window.
        anchor_idx = 0
        if obv_anchor_date:
            anchor_idx = next(
                (i for i, b in enumerate(bars) if str(b.get("date", "")) >= obv_anchor_date), -1
            )
        if anchor_idx < 0:
            sections.append(
                f"**OBV:** anchor {obv_anchor_date} is past the last bar ({latest_date}) — "
                "nothing to accumulate"
            )
        elif obv_anchor_date and anchor_idx >= len(bars) - 1:
            sections.append(
                f"**OBV:** anchor {obv_anchor_date} resolves to the last bar ({latest_date}) — "
                "no bars of flow since"
            )
        else:
            obv_vals = ta.obv(bars, anchor_idx)
            prior_idx = anchor_idx if obv_anchor_date else len(bars) - 21
            cur = obv_vals[-1]
            prior = obv_vals[prior_idx] if prior_idx >= 0 else None
            if cur is not None and prior is not None:
                obv_chg = cur - prior
                price_prior = closes[prior_idx]
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
                if obv_anchor_date:
                    span = f"since {bars[anchor_idx].get('date', obv_anchor_date)}"
                    span += f" ({len(bars) - 1 - anchor_idx} bars)"
                else:
                    span = "20d"
                sections.append(
                    f"**OBV:** {span} Δ={obv_chg:+,.0f} vs price {price_chg_pct:+.1f}% — {tag}"
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
