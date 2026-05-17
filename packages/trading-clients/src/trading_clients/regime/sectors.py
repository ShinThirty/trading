"""SPDR sector rotation + semi-divergence detector."""

from ._common import _pct_return

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Tech",
    "XLF": "Fins",
    "XLE": "Energy",
    "XLV": "Health",
    "XLC": "Comm",
    "XLI": "Indust",
    "XLB": "Matls",
    "XLRE": "RE",
    "XLP": "Staples",
    "XLY": "Discret",
    "XLU": "Utils",
}

RISK_ON_ETFS = {"XLK", "XLY", "XLC"}
RISK_OFF_ETFS = {"XLU", "XLP", "XLRE"}


def classify_sector_rotation(
    sector_closes: dict[str, list[float]],
    windows: tuple[int, ...] = (30, 60, 90),
) -> tuple[str, str]:
    """Classify sector rotation from multi-timeframe ETF performance.

    Computes returns at multiple lookback windows for each SPDR sector ETF,
    ranks sectors, detects leadership shifts, and classifies risk appetite.

    sector_closes: {ETF_symbol: daily_closes_oldest_first} for sector ETFs.
    windows: lookback periods in trading days (default 30, 60, 90).

    Returns (label, detail_string) where label is Risk-On / Rotation / Risk-Off.
    """
    short_window = windows[0]
    long_window = windows[-1]

    returns: dict[int, dict[str, float]] = {}
    for w in windows:
        w_rets: dict[str, float] = {}
        for sym, closes in sector_closes.items():
            ret = _pct_return(closes, w)
            if ret is not None:
                w_rets[sym] = ret
        returns[w] = w_rets

    short_rets = returns.get(short_window, {})
    if len(short_rets) < 6:
        return "Unknown", "insufficient sector data"

    risk_on_vals = [short_rets[s] for s in RISK_ON_ETFS if s in short_rets]
    risk_off_vals = [short_rets[s] for s in RISK_OFF_ETFS if s in short_rets]
    risk_on_avg = sum(risk_on_vals) / len(risk_on_vals) if risk_on_vals else 0
    risk_off_avg = sum(risk_off_vals) / len(risk_off_vals) if risk_off_vals else 0

    if risk_on_avg > risk_off_avg and risk_on_avg > 0:
        label = "Risk-On"
    elif risk_off_avg > risk_on_avg and risk_off_avg > 0:
        label = "Risk-Off"
    else:
        label = "Rotation"

    ranked = sorted(short_rets.items(), key=lambda x: x[1], reverse=True)
    top3 = ranked[:3]
    bottom3 = ranked[-3:]

    name = SECTOR_ETFS.get
    top_str = ", ".join(f"{name(s, s)} {r:+.1f}%" for s, r in top3)
    bot_str = ", ".join(f"{name(s, s)} {r:+.1f}%" for s, r in bottom3)
    detail = f"{short_window}d leaders: {top_str}; laggards: {bot_str}"

    long_rets = returns.get(long_window, {})
    if len(long_rets) >= 6:
        ranked_long = sorted(long_rets.items(), key=lambda x: x[1], reverse=True)
        long_ranks = {sym: i + 1 for i, (sym, _) in enumerate(ranked_long)}
        short_ranks = {sym: i + 1 for i, (sym, _) in enumerate(ranked)}

        shifts = []
        for sym in sector_closes:
            if sym in long_ranks and sym in short_ranks:
                delta = long_ranks[sym] - short_ranks[sym]
                if delta >= 4:
                    shifts.append(
                        f"{name(sym, sym)} emerging (#{long_ranks[sym]}→#{short_ranks[sym]})"
                    )
                elif delta <= -4:
                    shifts.append(
                        f"{name(sym, sym)} fading (#{long_ranks[sym]}→#{short_ranks[sym]})"
                    )

        if shifts:
            detail += f"; shifts ({long_window}d→{short_window}d): {', '.join(shifts)}"

    return label, detail


def detect_semi_divergence(
    smh_closes: list[float],
    spy_closes: list[float],
    lookback: int = 20,
) -> str | None:
    """Detect semiconductor divergence from broad market.

    Big Tech (AAPL, MSFT) can mask semi weakness, producing a false
    Risk-On signal while semis are rolling over. Compare SMH vs SPY
    relative performance over the lookback period.

    smh_closes / spy_closes: daily closes (oldest first), at least
    lookback+1 bars.

    Returns a warning string, or None if no divergence.
    """
    if len(smh_closes) < lookback + 1 or len(spy_closes) < lookback + 1:
        return None

    smh_return = (smh_closes[-1] - smh_closes[-1 - lookback]) / smh_closes[-1 - lookback] * 100
    spy_return = (spy_closes[-1] - spy_closes[-1 - lookback]) / spy_closes[-1 - lookback] * 100
    divergence = smh_return - spy_return

    # Flag if SMH underperforms SPY by more than 3% over the lookback period
    if divergence < -3.0:
        return (
            f"Semi divergence: SMH {smh_return:+.1f}% vs SPY {spy_return:+.1f}% "
            f"({lookback}d) — cycle may be turning despite Risk-On sector label"
        )

    return None
