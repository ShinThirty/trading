"""SqueezeMetrics DIX/GEX tool.

Surfaces dark-pool accumulation (DIX) + dealer gamma (GEX) as a biweekly
macro overlay alongside `get_market_regime`. The actionable framing is the
2x2 regime cell (DIX high/low × GEX positive/negative), supplemented by
price/DIX divergence detection — not the raw values in isolation.

Outputs in order:
  1. Latest snapshot with regime labels
  2. 2x2 regime cell + one-line implication
  3. Divergence flag (only if 10-day SPX move and DIX delta have opposing signs)
  4. 10-day micro trend table
  5. Multi-window percentile context (1m/3m/6m/1y)
  6. Source + caveats

DIX is dollar-weighted dark-pool short volume of S&P 500 components; "short"
here is the brokers' reporting convention, not directional shorting — high
DIX historically preceded positive forward returns (per SqueezeMetrics 2017
white paper) because it reflects MMs absorbing aggressive sells from
institutional buyers accumulating off-exchange.

GEX tells you HOW the market will respond to flow (vol-suppressing vs
vol-amplifying), not what the flow will be. Today's value also gates whether
short-vol structures (CSPs, ICs) are well-priced for the current regime.
"""

from fastmcp import Context, FastMCP
from trading_clients.endpoints import squeeze_metrics
from trading_clients.endpoints.squeeze_metrics import DixRow
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _squeeze_metrics

mcp = FastMCP("squeeze-metrics-tools")

# Thresholds. The 0.45/0.40 DIX bands trace to the SqueezeMetrics 2017 paper
# (≥0.45 = bullish; ≤0.40 = bearish/uncertain); the in-between band is treated
# as neutral. GEX uses sign only for the regime cell (magnitude is shown
# separately for context).
DIX_HIGH = 0.45
DIX_LOW = 0.40

# Divergence sensitivity. Below these magnitudes the move isn't large enough
# to call a direction; setting both thresholds prevents flagging noise.
DIVERGENCE_SPX_PCT = 2.0
DIVERGENCE_DIX_ABS = 0.02


def _dix_label(dix: float) -> str:
    if dix >= DIX_HIGH:
        return "Bullish (institutional accumulation)"
    if dix >= DIX_LOW:
        return "Neutral"
    return "Bearish (no accumulation / distribution)"


def _gex_label(gex: float) -> str:
    if gex > 0:
        return "Positive (dealers vol-suppressing — buy dips, sell rallies)"
    return "Negative (dealers vol-amplifying — sell dips, buy rallies)"


def _fmt_gex(gex: float) -> str:
    sign = "+" if gex >= 0 else "-"
    return f"{sign}${abs(gex) / 1e9:.2f}B"


def _regime_cell(dix: float, gex: float) -> tuple[str, str]:
    """Return (cell label, one-line implication) for the DIX×GEX 2x2."""
    dix_high = dix >= DIX_HIGH
    dix_low = dix < DIX_LOW
    gex_pos = gex > 0

    if dix_high and gex_pos:
        return (
            "DIX high · GEX positive",
            "Accumulation in stable tape. Favors CSPs / iron condors and "
            "accumulation entries on minor dips.",
        )
    if dix_high and not gex_pos:
        return (
            "DIX high · GEX negative",
            "Buying through volatility — often near major lows. Accumulation "
            "favorable; don't expect IV to compress fast.",
        )
    if dix_low and gex_pos:
        return (
            "DIX low · GEX positive",
            "No accumulation but vol suppressed — range-bound chop. Favors "
            "iron condors; unfavorable for directional accumulation.",
        )
    if dix_low and not gex_pos:
        return (
            "DIX low · GEX negative",
            "Distribution + amplification. Bearish setup — favor hedges, "
            "avoid new long-delta exposure.",
        )
    # Neutral DIX band — describe with a softer reading.
    posture = "vol-suppressed" if gex_pos else "vol-amplified"
    return (
        f"DIX neutral · GEX {'positive' if gex_pos else 'negative'}",
        f"DIX in the 0.40-0.45 transition band; dealer book {posture}. "
        "No strong bias from this overlay alone.",
    )


def _divergence(rows: list[DixRow]) -> str | None:
    """Flag opposing 10-day moves in SPX and DIX. Returns the markdown line
    if a real divergence exists, else None."""
    if len(rows) < 11:
        return None
    a, b = rows[-11], rows[-1]
    spx_pct = (b.price / a.price - 1.0) * 100 if a.price else 0.0
    dix_delta = b.dix - a.dix

    if abs(spx_pct) < DIVERGENCE_SPX_PCT or abs(dix_delta) < DIVERGENCE_DIX_ABS:
        return None
    if (spx_pct > 0) == (dix_delta > 0):
        return None

    if spx_pct > 0:
        # Up tape, falling DIX → distribution into strength
        return (
            f"⚠ **Bearish divergence** — SPX +{spx_pct:.1f}% over the last 10 sessions "
            f"while DIX dropped {dix_delta:+.3f} ({a.dix:.3f}→{b.dix:.3f}). "
            "Distribution into strength: institutions selling/lightening into the rally."
        )
    # Down tape, rising DIX → accumulation into weakness
    return (
        f"⚠ **Bullish divergence** — SPX {spx_pct:.1f}% over the last 10 sessions "
        f"while DIX rose {dix_delta:+.3f} ({a.dix:.3f}→{b.dix:.3f}). "
        "Accumulation into weakness: institutions buying through the drawdown."
    )


def _percentile(values: list[float], target: float) -> float:
    """Rank-based percentile of `target` within `values`. Returns 0-100."""
    n = len(values)
    if n == 0:
        return 0.0
    below = sum(1 for v in values if v < target)
    return below / n * 100


def _window_stats(
    rows: list[DixRow], days: int, attr: str
) -> tuple[float, float]:
    """Return (mean, latest_percentile) for trailing `days` window."""
    window = rows[-days:] if len(rows) >= days else rows
    values = [getattr(r, attr) for r in window]
    latest = values[-1]
    mean = sum(values) / len(values)
    return mean, _percentile(values, latest)


@mcp.tool()
async def get_dix_gex(ctx: Context) -> str:
    """Get the latest SqueezeMetrics DIX (dark-pool sentiment) and GEX (dealer
    gamma exposure) plus the 2x2 regime cell, divergence flag, 10-day trend,
    and multi-window percentile context.

    Surfaces in order:
      - Latest snapshot (date, SPX close, DIX, GEX) with regime labels.
      - 2x2 regime cell (DIX high/low × GEX positive/negative) + one-line
        implication for short-vol structures, accumulation, hedges.
      - Divergence flag — only present when 10-day SPX move and DIX delta
        have opposing signs (the highest-signal pattern: distribution into
        strength or accumulation into weakness).
      - 10-day micro trend (date / SPX / DIX / GEX).
      - Multi-window percentile context (1m / 3m / 6m / 1y) showing today's
        value's rank within each trailing window.

    DIX is dollar-weighted S&P 500 dark-pool short-volume ratio. "Short" is
    the broker reporting convention, not directional — high DIX = market
    makers absorbing aggressive sells from institutions accumulating off
    -exchange. Per SqueezeMetrics 2017 paper, DIX ≥ 0.45 historically
    preceded ~5% mean 60-day forward returns; predictive power softened
    post-2020 as retail wholesaler flow reshaped dark-pool composition.

    GEX is dollar-denominated dealer net gamma. Tells you HOW the market
    responds to flow, not what the flow will be: positive = dealers hedge
    against direction (suppresses realized vol); negative = dealers hedge
    with direction (amplifies vol — both drawdowns and squeezes more
    violent). Used to gate whether short-vol structures (CSPs, ICs) are
    well-priced for the current regime.

    Both signals move slowly and are intended for the biweekly macro/regime
    read, not for intraday tactics. Source: https://squeezemetrics.com/monitor/dix
    (free CSV behind the public chart).
    """
    client = _squeeze_metrics(ctx)
    history = await client.get(squeeze_metrics.DIX_HISTORY, squeeze_metrics.EmptyRequest())

    rows = history.rows
    if not rows:
        return "SqueezeMetrics DIX/GEX: no rows returned from upstream."

    latest = rows[-1]
    cell, implication = _regime_cell(latest.dix, latest.gex)

    out: list[str] = [
        f"## SqueezeMetrics DIX / GEX — {latest.date.isoformat()}",
        "",
        f"- **S&P 500 close**: {latest.price:,.2f}",
        f"- **DIX**: {latest.dix:.4f} → {_dix_label(latest.dix)}",
        f"- **GEX**: {_fmt_gex(latest.gex)} → {_gex_label(latest.gex)}",
        "",
        f"**Regime cell:** {cell}",
        "",
        implication,
        "",
    ]

    div = _divergence(rows)
    if div:
        out.append(div)
        out.append("")

    # 10-day micro trend
    trend_rows = rows[-10:]
    trend_table = md_table(
        ["Date", "SPX", "DIX", "GEX"],
        [
            [
                r.date.isoformat(),
                f"{r.price:,.2f}",
                f"{r.dix:.4f}",
                _fmt_gex(r.gex),
            ]
            for r in trend_rows
        ],
    )
    out.extend(["### 10-day micro trend", "", trend_table, ""])

    # Multi-window percentile context (~21 trading days/month)
    windows = [(21, "1m"), (63, "3m"), (126, "6m"), (252, "1y")]
    pctl_rows: list[list[str]] = []
    for days, label in windows:
        d_mean, d_pctl = _window_stats(rows, days, "dix")
        g_mean, g_pctl = _window_stats(rows, days, "gex")
        pctl_rows.append(
            [
                label,
                f"{d_mean:.4f}",
                f"{d_pctl:.0f}",
                _fmt_gex(g_mean),
                f"{g_pctl:.0f}",
            ]
        )
    pctl_table = md_table(
        ["Window", "DIX mean", "DIX %ile", "GEX mean", "GEX %ile"],
        pctl_rows,
    )
    out.extend(
        [
            "### Trailing-window context (latest value's percentile within window)",
            "",
            pctl_table,
            "",
            "_Source: squeezemetrics.com/monitor/dix · DIX bands and "
            "60-day return claim are SqueezeMetrics' 2017 methodology; "
            "post-2020 dark-pool composition has shifted with retail "
            "wholesaler flow. GEX is SqueezeMetrics' proprietary calculation; "
            "other vendors (SpotGamma, Tier1Alpha) compute different numbers._",
        ]
    )

    return "\n".join(out)


__all__ = ["mcp", "get_dix_gex"]
