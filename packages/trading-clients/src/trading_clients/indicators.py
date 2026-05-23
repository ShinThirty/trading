"""Technical analysis indicator computations on OHLCV bar data.

All functions take a list of bar dicts (with 'open', 'high', 'low', 'close', 'volume')
ordered oldest-first and return computed values aligned to the same indices. Every
indicator is O(N) in the number of bars; window-based statistics use rolling sums
or monotonic deques so the per-bar cost is constant in the window size.
"""

from collections import deque
from math import log, sqrt

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _volume(bar: dict) -> float:
    """Volume read that treats missing or null fields as 0."""
    v = bar.get("volume", 0)
    return float(v) if v else 0.0


def _typical_price(bar: dict) -> float:
    """HLC midpoint (high + low + close) / 3 — the basis for MFI and VWAP."""
    return (bar["high"] + bar["low"] + bar["close"]) / 3.0


def _wilder_avg_step(prev: float, value: float, period: int) -> float:
    """Wilder's smoothed *average* recurrence — equivalent to EMA(α=1/period).

    next = (prev * (period - 1) + value) / period. Used in RSI, ATR, and ADX (over DX).
    """
    return (prev * (period - 1) + value) / period


def _wilder_sum_step(prev: float, value: float, period: int) -> float:
    """Wilder's smoothed *sum* recurrence: next = prev - prev/period + value.

    Used inside ADX for the running TR / +DM / -DM totals (sum form, not average).
    """
    return prev - prev / period + value


def _rolling_extremum(values: list[float], period: int, find_max: bool) -> list[float | None]:
    """Sliding-window max (find_max=True) or min — O(N) total via monotonic deque."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period <= 0 or n == 0:
        return out
    dq: deque[int] = deque()
    for i, v in enumerate(values):
        while dq and dq[0] <= i - period:
            dq.popleft()
        if find_max:
            while dq and values[dq[-1]] <= v:
                dq.pop()
        else:
            while dq and values[dq[-1]] >= v:
                dq.pop()
        dq.append(i)
        if i >= period - 1:
            out[i] = values[dq[0]]
    return out


def _sma_of_optional(values: list[float | None], period: int) -> list[float | None]:
    """Rolling SMA over a sequence that may contain None — O(N).

    Emits None unless the entire `period`-wide window is non-None. Matches the
    stacked-SMA smoothing used in Stochastic RSI's %K / %D pipeline.
    """
    n = len(values)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return out
    s = 0.0
    none_count = 0
    for i in range(n):
        v = values[i]
        if v is None:
            none_count += 1
        else:
            s += v
        if i >= period:
            old = values[i - period]
            if old is None:
                none_count -= 1
            else:
                s -= old
        if i >= period - 1 and none_count == 0:
            out[i] = s / period
    return out


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def sma(closes: list[float], period: int) -> list[float | None]:
    """Simple Moving Average — O(N) via a single rolling sum."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return result
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= period:
            s -= closes[i - period]
        if i >= period - 1:
            result[i] = s / period
    return result


def ema(closes: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average — α = 2/(period+1), SMA-seeded."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    multiplier = 2.0 / (period + 1)
    prev = sum(closes[:period]) / period
    result[period - 1] = prev
    for i in range(period, n):
        prev = (closes[i] - prev) * multiplier + prev
        result[i] = prev
    return result


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index — Wilder's smoothing."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        avg_gain += max(delta, 0.0)
        avg_loss += max(-delta, 0.0)
    avg_gain /= period
    avg_loss /= period

    result[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        delta = closes[i] - closes[i - 1]
        avg_gain = _wilder_avg_step(avg_gain, max(delta, 0.0), period)
        avg_loss = _wilder_avg_step(avg_loss, max(-delta, 0.0), period)
        result[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return result


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line, signal line, and histogram."""
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)

    macd_line: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        f, s = fast_ema[i], slow_ema[i]
        if f is not None and s is not None:
            macd_line[i] = f - s

    macd_vals = [v for v in macd_line if v is not None]
    signal_ema = ema(macd_vals, signal_period) if len(macd_vals) >= signal_period else []

    signal_line: list[float | None] = [None] * len(closes)
    histogram: list[float | None] = [None] * len(closes)
    j = 0
    for i in range(len(closes)):
        m = macd_line[i]
        if m is not None:
            sig = signal_ema[j] if j < len(signal_ema) else None
            if sig is not None:
                signal_line[i] = sig
                histogram[i] = m - sig
            j += 1
    return macd_line, signal_line, histogram


def bollinger_bands(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger Bands — O(N) via rolling sum + rolling sum-of-squares."""
    n = len(closes)
    upper: list[float | None] = [None] * n
    middle: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return upper, middle, lower

    s = 0.0
    s2 = 0.0
    for i, c in enumerate(closes):
        s += c
        s2 += c * c
        if i >= period:
            old = closes[i - period]
            s -= old
            s2 -= old * old
        if i >= period - 1:
            mean = s / period
            # max(..., 0.0) clamps the tiny negative drift the two-pass formula
            # can produce when sum_sq ≈ n·mean² (numerically identical windows).
            var = max(s2 / period - mean * mean, 0.0)
            std = sqrt(var)
            middle[i] = mean
            upper[i] = mean + num_std * std
            lower[i] = mean - num_std * std
    return upper, middle, lower


def log_returns(closes: list[float]) -> list[float]:
    """Daily log returns from a list of closing prices (oldest-first)."""
    return [log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def beta(
    asset_bars: list[dict],
    benchmark_bars: list[dict],
    min_points: int = 20,
) -> float | None:
    """OLS beta of an asset vs a benchmark, aligned by date.

    Each bar must have 'date' and 'close' keys. Bars are aligned on matching
    dates to avoid misalignment from trading halts or API gaps.
    Returns None if fewer than min_points aligned data points.
    """
    asset_by_date = {b["date"]: b["close"] for b in asset_bars}
    bench_by_date = {b["date"]: b["close"] for b in benchmark_bars}
    common = sorted(asset_by_date.keys() & bench_by_date.keys())
    if len(common) < min_points + 1:
        return None
    a_closes = [asset_by_date[d] for d in common]
    b_closes = [bench_by_date[d] for d in common]
    a_ret = log_returns(a_closes)
    b_ret = log_returns(b_closes)
    mean_a = sum(a_ret) / len(a_ret)
    mean_b = sum(b_ret) / len(b_ret)
    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(a_ret, b_ret)) / len(a_ret)
    var_b = sum((b - mean_b) ** 2 for b in b_ret) / len(b_ret)
    if var_b == 0:
        return None
    return cov / var_b


def atr(bars: list[dict], period: int = 14) -> list[float | None]:
    """Average True Range — Wilder's smoothing of true range."""
    n = len(bars)
    result: list[float | None] = [None] * n
    if n < 2 or n < period:
        return result

    tr: list[float] = [bars[0]["high"] - bars[0]["low"]]
    for i in range(1, n):
        h, lo, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr.append(max(h - lo, abs(h - pc), abs(lo - pc)))

    current = sum(tr[:period]) / period
    result[period - 1] = current
    for i in range(period, n):
        current = _wilder_avg_step(current, tr[i], period)
        result[i] = current
    return result


def adx(
    bars: list[dict], period: int = 14
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Average Directional Index plus +DI and -DI (Wilder's smoothing).

    Returns (adx_values, plus_di, minus_di). ADX measures trend strength regardless
    of direction; +DI/-DI together identify direction. Conventional reads:
      ADX <20 → ranging, 20-25 transitional, >25 trending, >40 strong trend.
      +DI > -DI → uptrend bias; -DI > +DI → downtrend bias.
    """
    n = len(bars)
    adx_out: list[float | None] = [None] * n
    plus_di_out: list[float | None] = [None] * n
    minus_di_out: list[float | None] = [None] * n
    if n < 2 * period + 1:
        return adx_out, plus_di_out, minus_di_out

    tr: list[float] = [0.0]
    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    for i in range(1, n):
        h, lo = bars[i]["high"], bars[i]["low"]
        ph, pl, pc = bars[i - 1]["high"], bars[i - 1]["low"], bars[i - 1]["close"]
        tr.append(max(h - lo, abs(h - pc), abs(lo - pc)))
        up, down = h - ph, pl - lo
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    smooth_tr = sum(tr[1 : period + 1])
    smooth_plus = sum(plus_dm[1 : period + 1])
    smooth_minus = sum(minus_dm[1 : period + 1])

    dx_values: list[float] = []

    def _emit_di(i: int) -> None:
        if smooth_tr == 0:
            plus_di_out[i] = 0.0
            minus_di_out[i] = 0.0
            dx_values.append(0.0)
            return
        pdi = 100.0 * smooth_plus / smooth_tr
        mdi = 100.0 * smooth_minus / smooth_tr
        plus_di_out[i] = pdi
        minus_di_out[i] = mdi
        denom = pdi + mdi
        dx_values.append(100.0 * abs(pdi - mdi) / denom if denom else 0.0)

    _emit_di(period)
    for i in range(period + 1, n):
        smooth_tr = _wilder_sum_step(smooth_tr, tr[i], period)
        smooth_plus = _wilder_sum_step(smooth_plus, plus_dm[i], period)
        smooth_minus = _wilder_sum_step(smooth_minus, minus_dm[i], period)
        _emit_di(i)

    if len(dx_values) < period:
        return adx_out, plus_di_out, minus_di_out
    current_adx = sum(dx_values[:period]) / period
    adx_out[2 * period - 1] = current_adx
    for k in range(period, len(dx_values)):
        current_adx = _wilder_avg_step(current_adx, dx_values[k], period)
        adx_out[period + k] = current_adx
    return adx_out, plus_di_out, minus_di_out


def obv(bars: list[dict]) -> list[float | None]:
    """On-Balance Volume — cumulative signed volume.

    Up-close bars add volume; down-close bars subtract; flat closes unchanged.
    Useful for divergence reads (price up + OBV flat = distribution; price down +
    OBV up = accumulation).
    """
    n = len(bars)
    result: list[float | None] = [None] * n
    if n == 0:
        return result
    running = 0.0
    result[0] = 0.0
    for i in range(1, n):
        close = bars[i]["close"]
        prev_close = bars[i - 1]["close"]
        vol = _volume(bars[i])
        if close > prev_close:
            running += vol
        elif close < prev_close:
            running -= vol
        result[i] = running
    return result


def donchian(
    bars: list[dict], period: int = 20
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Donchian channels: highest high, lowest low, and midline over N bars — O(N).

    Period defaults to 20 (Turtle tactical). For structural levels, call with
    period=55. Sliding extrema computed with a monotonic deque.
    """
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    upper = _rolling_extremum(highs, period, find_max=True)
    lower = _rolling_extremum(lows, period, find_max=False)
    middle: list[float | None] = [
        (u + lo) / 2 if (u is not None and lo is not None) else None for u, lo in zip(upper, lower)
    ]
    return upper, middle, lower


def mfi(bars: list[dict], period: int = 14) -> list[float | None]:
    """Money Flow Index — volume-weighted RSI on typical price — O(N).

    0-100 scale; <20 oversold, >80 overbought. Captures buying/selling pressure that
    price-only RSI misses on low-float and post-IPO names.
    """
    n = len(bars)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    tp = [_typical_price(b) for b in bars]
    pos_mf = [0.0] * n
    neg_mf = [0.0] * n
    for k in range(1, n):
        mf = tp[k] * _volume(bars[k])
        if tp[k] > tp[k - 1]:
            pos_mf[k] = mf
        elif tp[k] < tp[k - 1]:
            neg_mf[k] = mf

    pos_sum = 0.0
    neg_sum = 0.0
    for i in range(1, n):
        pos_sum += pos_mf[i]
        neg_sum += neg_mf[i]
        if i >= period + 1:
            pos_sum -= pos_mf[i - period]
            neg_sum -= neg_mf[i - period]
        if i >= period:
            result[i] = 100.0 if neg_sum == 0 else 100.0 - 100.0 / (1.0 + pos_sum / neg_sum)
    return result


def stochastic_rsi(
    closes: list[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> tuple[list[float | None], list[float | None]]:
    """Stochastic RSI — stochastic oscillator applied to RSI values — O(N).

    Returns (%K, %D) on 0-100 scale. <20 oversold, >80 overbought. Faster than
    plain RSI for catching short-term extremes (capitulation, exhaustion).
    """
    n = len(closes)
    rsi_vals = rsi(closes, rsi_period)
    raw_k: list[float | None] = [None] * n

    # RSI fills contiguously from index `rsi_period` onward — the suffix has no None.
    first = next((i for i, v in enumerate(rsi_vals) if v is not None), None)
    if first is not None and n - first >= stoch_period:
        valid = [v for v in rsi_vals[first:] if v is not None]
        hi_w = _rolling_extremum(valid, stoch_period, find_max=True)
        lo_w = _rolling_extremum(valid, stoch_period, find_max=False)
        for j, (hi, lo) in enumerate(zip(hi_w, lo_w)):
            if hi is None or lo is None:
                continue
            cur = valid[j]
            raw_k[first + j] = 50.0 if hi == lo else 100.0 * (cur - lo) / (hi - lo)

    k_smoothed = _sma_of_optional(raw_k, smooth_k)
    d_smoothed = _sma_of_optional(k_smoothed, smooth_d)
    return k_smoothed, d_smoothed


def historical_volatility(closes: list[float], period: int = 30) -> list[float | None]:
    """Annualized realized (close-to-close log-return) volatility over N bars — O(N).

    Returned as percent (e.g. 28.5 = 28.5%). Annualization factor √252 (daily bars).
    Call with multiple periods (10/30/60) to read the HV term structure.
    """
    n = len(closes)
    result: list[float | None] = [None] * n
    if period <= 0 or n < period + 1:
        return result
    rets = log_returns(closes)  # length n - 1, aligned to closes[1..]
    annualize = sqrt(252) * 100.0

    s = 0.0
    s2 = 0.0
    for i, r in enumerate(rets):
        s += r
        s2 += r * r
        if i >= period:
            old = rets[i - period]
            s -= old
            s2 -= old * old
        if i >= period - 1:
            mean = s / period
            var = max(s2 / period - mean * mean, 0.0)
            result[i + 1] = sqrt(var) * annualize
    return result


def anchored_vwap(bars: list[dict], anchor_index: int = 0) -> list[float | None]:
    """Anchored VWAP — cumulative VWAP starting from `anchor_index`.

    Acts as institutional cost-basis level from the anchor date forward. Bars before
    the anchor receive None. Typical price (HLC/3) × volume / cumulative volume.
    """
    n = len(bars)
    result: list[float | None] = [None] * n
    if anchor_index >= n:
        return result
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for i in range(anchor_index, n):
        tp = _typical_price(bars[i])
        vol = _volume(bars[i])
        cum_tp_vol += tp * vol
        cum_vol += vol
        if cum_vol > 0:
            result[i] = cum_tp_vol / cum_vol
        elif i > anchor_index:
            result[i] = result[i - 1]
        else:
            result[i] = bars[i]["close"]
    return result
