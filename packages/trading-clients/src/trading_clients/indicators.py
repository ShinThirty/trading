"""Technical analysis indicator computations on OHLCV bar data.

All functions take a list of bar dicts (with 'open', 'high', 'low', 'close', 'volume')
ordered oldest-first and return computed values aligned to the same indices.
"""

from math import sqrt


def sma(closes: list[float], period: int) -> list[float | None]:
    """Simple Moving Average."""
    result: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1 : i + 1]) / period
    return result


def ema(closes: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average."""
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period:
        return result
    multiplier = 2.0 / (period + 1)
    # Seed with SMA of first `period` values
    seed = sum(closes[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, len(closes)):
        val = (closes[i] - prev) * multiplier + prev
        result[i] = val
        prev = val
    return result


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index (Wilder's smoothing)."""
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    # Initial average gain/loss from first `period` changes
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)

    # Smoothed subsequent values (Wilder's method)
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - 100.0 / (1.0 + rs)

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

    # Signal = EMA of non-None MACD values
    macd_vals = [v for v in macd_line if v is not None]
    signal_ema = ema(macd_vals, signal_period) if len(macd_vals) >= signal_period else []

    signal_line: list[float | None] = [None] * len(closes)
    histogram: list[float | None] = [None] * len(closes)

    # Map signal EMA back to original indices
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
    """Bollinger Bands: upper, middle (SMA), lower."""
    middle = sma(closes, period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = middle[i]
        assert mean is not None
        variance = sum((x - mean) ** 2 for x in window) / period
        std = sqrt(variance)
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std

    return upper, middle, lower


def atr(bars: list[dict], period: int = 14) -> list[float | None]:
    """Average True Range."""
    result: list[float | None] = [None] * len(bars)
    if len(bars) < 2:
        return result

    # Compute true range for each bar (first bar has no prev close)
    tr_values: list[float] = [bars[0]["high"] - bars[0]["low"]]
    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        tr_values.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    if len(tr_values) < period:
        return result

    # Initial ATR is SMA of first `period` true ranges
    current_atr = sum(tr_values[:period]) / period
    result[period - 1] = current_atr

    # Smoothed subsequent values (Wilder's method)
    for i in range(period, len(tr_values)):
        current_atr = (current_atr * (period - 1) + tr_values[i]) / period
        result[i] = current_atr

    return result
