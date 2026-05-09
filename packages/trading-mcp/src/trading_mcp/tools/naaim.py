"""NAAIM Exposure Index history tool.

The NAAIM Exposure Index is a weekly survey of active manager equity
exposure (range -200 max-short to +200 max-long; typical 0-100). It moves
slowly and is most useful as a contrarian positioning gauge alongside CFTC
COT, AAII spread, and CBOE put/call.

This tool surfaces:
  1. Latest reading + week-over-week change.
  2. 52-week z-score and percentile (parallel to COT framing).
  3. Status label with contrarian polarity (extreme long = bearish-forward,
     extreme defensive = squeeze setup).
  4. Recent 8-week trend (NAAIM + SPX close from the same workbook).
  5. Multi-window percentile context (4w / 13w / 26w / 52w).

Source: NAAIM publishes a single since-inception XLSX republished every
Wednesday/Thursday. The client discovers the URL by scraping the program
page and downloads the workbook (~85KB, ~1k weekly rows since 2006).
"""

from statistics import mean
from typing import Literal

from fastmcp import Context, FastMCP
from trading_clients.endpoints.naaim import NaaimHistoryEntry, NaaimHistoryResponse
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _naaim

mcp = FastMCP("naaim-tools")


def _status_label(z: float | None) -> str:
    """Map z-score to extremity label with contrarian polarity.

    NAAIM is a positioning gauge: extreme long readings are crowded (bearish-
    forward), extreme defensive readings flag capitulation (squeeze setup).
    """
    if z is None:
        return "—"
    if z >= 2.0:
        return "🔴 GREEDY (crowded long — contrarian bearish)"
    if z >= 1.5:
        return "🟡 stretched long"
    if z <= -2.0:
        return "🔴 CAPITULATION (max defensive — contrarian bullish)"
    if z <= -1.5:
        return "🟡 stretched defensive"
    return "neutral"


def _absolute_label(value: float) -> str:
    """Plain reading on absolute exposure level (range -200..+200)."""
    if value >= 90:
        return "near max long, leveraged tilt"
    if value >= 70:
        return "largely invested"
    if value >= 50:
        return "moderately long"
    if value >= 30:
        return "underweight equities"
    if value >= 0:
        return "defensive"
    return "net short"


def _percentile(values: list[float], target: float) -> float:
    """Rank-based percentile of `target` within `values`."""
    n = len(values)
    if n == 0:
        return 0.0
    below = sum(1 for v in values if v < target)
    return below / n * 100


def _window_stats(entries: list[NaaimHistoryEntry], weeks: int) -> tuple[float, float] | None:
    """Return (mean, latest_percentile) for trailing `weeks` window. None if
    fewer than 4 weeks available."""
    window = entries[: min(len(entries), weeks)]
    if len(window) < 4:
        return None
    values = [e.exposure for e in window]
    return mean(values), _percentile(values, values[0])


def _format_trend(history: NaaimHistoryResponse, weeks: int = 8) -> str:
    rows: list[list[str]] = []
    for e in history.entries[:weeks]:
        spx = f"{e.spx_close:,.2f}" if e.spx_close is not None else "—"
        rows.append([e.week_ending.isoformat(), f"{e.exposure:.1f}", spx])
    return md_table(["Week ending", "Exposure", "S&P 500"], rows)


@mcp.tool()
async def get_naaim_history(ctx: Context, mode: Literal["summary", "trend"] = "summary") -> str:
    """Get the NAAIM Exposure Index — weekly active-manager equity exposure
    (range -200 to +200, typical 0-100) — with full historical context.

    Surfaces in order:
      - Latest reading (week-ending date, exposure, week-over-week change).
      - 52-week z-score and percentile, with a contrarian status label
        (Greedy/Stretched Long → bearish-forward; Capitulation/Stretched
        Defensive → squeeze setup).
      - Plain reading on the absolute level ("near max long", "defensive", etc.).
      - 8-week trend table (exposure + SPX close from the same workbook —
        useful for spotting divergence: managers de-risking into a rising
        index, or buying through a drawdown).
      - Multi-window percentile context (4w / 13w / 26w / 52w).

    NAAIM updates Wednesday afternoon for the prior week's positioning.
    Most useful at biweekly review cadence as a contrarian crowding gauge
    alongside CFTC COT, AAII spread, and CBOE put/call.

    mode: "summary" (default) shows the standard overview. "trend" returns
    just the recent 12-week trend table — useful when chaining into a
    larger briefing where the rest of the context is already on screen.
    """
    client = _naaim(ctx)
    history = await client.get_history()

    if not history.entries:
        return "NAAIM: no rows returned from upstream."

    if mode == "trend":
        return "## NAAIM Exposure — recent trend\n\n" + _format_trend(history, weeks=12)

    latest = history.latest
    assert latest is not None  # guarded by entries check above

    out: list[str] = [
        f"## NAAIM Exposure — {history.latest_date}",
        "",
        f"- **Exposure**: {latest.exposure:.1f} ({_absolute_label(latest.exposure)})",
    ]
    if history.wow_change is not None:
        out.append(f"- **Week-over-week Δ**: {history.wow_change:+.1f}")
    if history.trailing_mean is not None:
        out.append(f"- **52w mean**: {history.trailing_mean:.1f}")
    if history.z_score is not None:
        out.append(f"- **52w z-score**: {history.z_score:+.2f}")
    if history.percentile is not None:
        out.append(f"- **52w percentile**: {history.percentile:.0f}%")
    out.append("")
    out.append(f"**Status:** {_status_label(history.z_score)}")
    out.append("")

    out.append("### Recent 8-week trend")
    out.append("")
    out.append(_format_trend(history, weeks=8))
    out.append("")

    # Multi-window percentile context — where today sits in shorter windows
    # so a fresh extreme is distinguishable from a slow drift to the mean.
    windows = [(4, "4w"), (13, "13w"), (26, "26w"), (52, "52w")]
    rows: list[list[str]] = []
    for w, label in windows:
        stats = _window_stats(history.entries, w)
        if stats is None:
            continue
        mean_val, pctl = stats
        rows.append([label, f"{mean_val:.1f}", f"{pctl:.0f}"])
    if rows:
        out.append("### Trailing-window context (latest value's percentile within window)")
        out.append("")
        out.append(md_table(["Window", "Mean exposure", "Latest %ile"], rows))
        out.append("")

    out.append(
        "_Source: naaim.org/programs/naaim-exposure-index — weekly survey of "
        "NAAIM member managers' equity exposure. Released Wednesday afternoon "
        "for the prior week. Contrarian polarity: extreme long reads as "
        "crowded (bearish-forward); extreme defensive reads as capitulation "
        "(squeeze setup). Most useful at biweekly review cadence._"
    )

    return "\n".join(out)


__all__ = ["mcp", "get_naaim_history"]
