"""Container freight signals tool.

Combines Freightos Baltic Index (FBX) lane prices with IMF PortWatch
daily chokepoint transit volumes. The point is geopolitical-risk
*confirmation*: when a Red Sea / Hormuz / Panama headline hits, this
tool tells you whether ships are actually rerouting or just whether the
news cycle is loud.

Canonical Red Sea pattern: FBX China-Med + China-N Europe spike (Suez
detour adds ~10-14 days), Bab el-Mandeb daily transit count collapses,
Cape of Good Hope transits surge — three confirming signals within the
same week.

Surfaces the data; the regime call (real disruption vs noise spike)
happens in conversation.
"""

import asyncio
import statistics
from typing import Any

from fastmcp import Context, FastMCP
from trading_clients.endpoints import freight
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _exc_summary, _freightos, _portwatch

mcp = FastMCP("freight-tools")


def _warnings_section(warnings: list[str]) -> list[str]:
    if not warnings:
        return []
    lines = ["⚠ Data source warnings (some fetches failed):"]
    for w in warnings:
        lines.append(f"  • {w}")
    lines.append("")
    return lines


def _pct_delta(series: list[tuple[str, float]], lookback: int) -> float | None:
    """% change from `lookback` positions back to latest. Returns None if
    series is too short."""
    if len(series) <= lookback:
        return None
    cur = series[-1][1]
    prev = series[-1 - lookback][1]
    if prev == 0:
        return None
    return (cur / prev - 1.0) * 100


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%"


@mcp.tool()
async def get_freight_signals(ctx: Context) -> str:
    """Container freight texture: Freightos Baltic Index (FBX) lane prices
    + IMF PortWatch daily chokepoint transit volumes.

    Use this to confirm geopolitical-risk rerouting. The tool surfaces
    three correlated views; the call (real disruption vs noise spike)
    happens in conversation.

    Returns:
      - **FBX lane table**: latest USD/FEU + 1w/4w/8w deltas for the
        global index plus 4 high-signal Asia-Western lanes. Suez-routed
        lanes (FBX13 China-Med, FBX11 China-N Europe) are most sensitive
        to Red Sea disruption. Panama-routed FBX01 (China-NAm WC) is most
        sensitive to Panama Canal stress. (Page embeds ~12 weeks of
        weekly history — longer windows aren't available without
        executing the page's JS.)
      - **Chokepoint table**: 7-day mean total + container vessel counts
        per chokepoint vs trailing-year baseline, with % deviation. ⚠ flag
        when |Δ| ≥ 25%. Suez/Bab el-Mandeb collapse + Cape of Good Hope
        surge = canonical reroute pattern.
      - **Latest-day per chokepoint**: the most recent daily snapshot
        (PortWatch publishes daily with ~5-day lag).

    Use cadence: call when a geopolitical headline is in play (Red Sea,
    Strait of Hormuz, Panama drought, Bosporus). The chokepoint deviation
    table is mostly noise when nothing is happening.

    Sources: Freightos (www.freightos.com terminal pages, weekly Friday
    publication) + IMF PortWatch (services9.arcgis.com Daily_Chokepoints_
    Data layer, daily with ~5-day lag). No auth required for either.
    """
    freightos = _freightos(ctx)
    portwatch = _portwatch(ctx)

    fbx_targets: list[freight.FbxLane] = [freight.FBX_GLOBAL] + list(freight.FBX_LANES.values())
    fbx_tasks = [
        freightos.get(freight.FREIGHTOS_FBX_PAGE, freight.FreightosLanePathRequest(slug=lane.slug))
        for lane in fbx_targets
    ]
    chokepoint_keys = list(freight.CHOKEPOINTS.keys())
    chokepoint_tasks = [
        portwatch.get(
            freight.PORTWATCH_CHOKEPOINTS_QUERY,
            freight.ChokepointQueryRequest(portname=freight.CHOKEPOINTS[k].portname),
        )
        for k in chokepoint_keys
    ]
    # Combined gather: list[Any] homogenizes the type so the type checker
    # doesn't latch the FreightosPageResponse shape onto chokepoint slots.
    all_tasks: list[Any] = [*fbx_tasks, *chokepoint_tasks]
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    warnings: list[str] = []
    fbx_responses: dict[str, freight.FreightosPageResponse | None] = {}
    for i, lane in enumerate(fbx_targets):
        r = results[i]
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(f"Freightos {lane.ticker} ({lane.label})", r))
            fbx_responses[lane.ticker] = None
        else:
            fbx_responses[lane.ticker] = r

    chokepoint_responses: dict[str, freight.ChokepointDataResponse | None] = {}
    for j, key in enumerate(chokepoint_keys):
        r = results[len(fbx_tasks) + j]
        cp = freight.CHOKEPOINTS[key]
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(f"PortWatch {cp.label}", r))
            chokepoint_responses[key] = None
        else:
            chokepoint_responses[key] = r

    out: list[str] = []
    out.extend(_warnings_section(warnings))

    # ─────────────────────────────────────────────────────────
    # Headline: latest FBX Global + most-stressed chokepoint
    # ─────────────────────────────────────────────────────────
    out.append("=== Headline ===")
    global_resp = fbx_responses.get(freight.FBX_GLOBAL.ticker)
    global_series: list[tuple[str, float]] = []
    if global_resp:
        global_series = global_resp.history_for(freight.FBX_GLOBAL.ticker)
    if global_series:
        d, v = global_series[-1]
        wk = _pct_delta(global_series, 1)
        m4 = _pct_delta(global_series, 4)
        m8 = _pct_delta(global_series, 8)
        out.append(
            f"Latest FBX Global: {v:.1f} USD/FEU ({d})"
            f"  {_fmt_pct(wk)} wk  {_fmt_pct(m4)} 4w  {_fmt_pct(m8)} 8w"
        )
    else:
        out.append("Latest FBX Global: (unavailable)")

    most_stressed: tuple[str, float, int, int] | None = None  # (label, dev_pct, 7d_total, ty_avg)
    for key in chokepoint_keys:
        resp = chokepoint_responses.get(key)
        if not resp or not resp.observations:
            continue
        cp = freight.CHOKEPOINTS[key]
        rows = resp.observations
        last7 = rows[-7:] if len(rows) >= 7 else rows
        ty = rows
        if not last7 or not ty:
            continue
        avg7 = statistics.mean(r.n_total for r in last7)
        avg_ty = statistics.mean(r.n_total for r in ty)
        if avg_ty == 0:
            continue
        dev = (avg7 - avg_ty) / avg_ty * 100
        if most_stressed is None or abs(dev) > abs(most_stressed[1]):
            most_stressed = (cp.label, dev, round(avg7), round(avg_ty))
    if most_stressed:
        label, dev, a7, aty = most_stressed
        out.append(
            f"Most-stressed chokepoint: {label} {dev:+.0f}% vs trailing year "
            f"(7d_avg={a7}/day vs TY_avg={aty}/day)"
        )
    out.append("")

    # ─────────────────────────────────────────────────────────
    # FBX lane table
    # ─────────────────────────────────────────────────────────
    out.append("=== FBX lane prices (USD/FEU; weekly history; deltas vs N weeks back) ===")
    fbx_rows: list[list[str]] = []
    for lane in fbx_targets:
        resp = fbx_responses.get(lane.ticker)
        series = resp.history_for(lane.ticker) if resp else []
        if not series:
            fbx_rows.append([f"{lane.label} ({lane.ticker})", "—", "—", "—", "—", "—"])
            continue
        d, v = series[-1]
        fbx_rows.append(
            [
                f"{lane.label} ({lane.ticker})",
                f"{v:,.1f}",
                d,
                _fmt_pct(_pct_delta(series, 1)),
                _fmt_pct(_pct_delta(series, 4)),
                _fmt_pct(_pct_delta(series, 8)),
            ]
        )
    out.append(md_table(["Lane", "Latest", "Date", "1w", "4w", "8w"], fbx_rows))

    # ─────────────────────────────────────────────────────────
    # Chokepoint deviation table
    # ─────────────────────────────────────────────────────────
    out.append("")
    out.append(
        "=== Chokepoint daily transit volumes "
        "(7d avg vs trailing-year baseline; ⚠ flags |Δ| ≥ 25%) ==="
    )
    cp_rows: list[list[str]] = []
    for key in chokepoint_keys:
        cp = freight.CHOKEPOINTS[key]
        resp = chokepoint_responses.get(key)
        if not resp or not resp.observations:
            cp_rows.append([cp.label, cp.region, "—", "—", "—", "—"])
            continue
        rows = resp.observations
        last7 = rows[-7:] if len(rows) >= 7 else rows
        ty = rows
        avg7_total = statistics.mean(r.n_total for r in last7)
        avg7_container = statistics.mean(r.n_container for r in last7)
        avg_ty = statistics.mean(r.n_total for r in ty) if ty else 0
        if avg_ty:
            dev = (avg7_total - avg_ty) / avg_ty * 100
            dev_str = f"{dev:+.0f}%"
            if abs(dev) >= 25:
                dev_str += " ⚠"
        else:
            dev_str = "—"
        cp_rows.append(
            [
                cp.label,
                cp.region,
                f"{avg7_total:.1f}",
                f"{avg_ty:.1f}",
                dev_str,
                f"{avg7_container:.1f}",
            ]
        )
    out.append(
        md_table(
            ["Chokepoint", "Region", "7d_total", "TY_avg", "Δ%", "7d_container"],
            cp_rows,
        )
    )

    # ─────────────────────────────────────────────────────────
    # Latest-day per chokepoint (PortWatch ~5-day lag)
    # ─────────────────────────────────────────────────────────
    out.append("")
    out.append("=== Latest day per chokepoint ===")
    for key in chokepoint_keys:
        cp = freight.CHOKEPOINTS[key]
        resp = chokepoint_responses.get(key)
        if not resp or not resp.observations:
            out.append(f"  {cp.label:20s} (no data)")
            continue
        last = resp.observations[-1]
        cap_m = last.capacity / 1e6
        out.append(
            f"  {cp.label:20s} {last.date}  container={last.n_container:>3}  "
            f"total={last.n_total:>3}  capacity={cap_m:.2f}M"
        )

    return "\n".join(out)


__all__ = ["mcp", "get_freight_signals"]
