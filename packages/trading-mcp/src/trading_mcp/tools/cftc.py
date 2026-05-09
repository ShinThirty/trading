"""CFTC Commitments of Traders (COT) tools.

Surfaces speculator positioning across a curated set of futures contracts so
positioning extremes — fade signals on the long side, squeeze risk on the
short side — can be flagged before they show up in price.
"""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients.endpoints import cftc
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _cftc, _exc_summary

mcp = FastMCP("cftc-tools")


def _status_label(z: float | None) -> str:
    """Map z-score to a human-readable extremity label."""
    if z is None:
        return "—"
    if z >= 2.0:
        return "🔴 CROWDED LONG"
    if z >= 1.5:
        return "🟡 stretched long"
    if z <= -2.0:
        return "🔴 CROWDED SHORT"
    if z <= -1.5:
        return "🟡 stretched short"
    return "neutral"


def _resolve_contract(contract: str) -> tuple[str, str, str] | None:
    """Look up (report_key, market_pattern, label) by friendly contract key."""
    return cftc.CONTRACTS.get(contract.upper())


@mcp.tool()
async def get_cot_positioning(ctx: Context, contract: str) -> str:
    """Get speculator positioning detail for one futures contract from the
    weekly CFTC Commitments of Traders report.

    Net spec positioning (long − short) is reported with week-over-week change,
    52-week z-score, and 52-week percentile. Extreme readings (|z| > 2) flag
    crowded positioning and serve as contrarian fade signals — crowded long is
    a setup for downside vulnerability; crowded short is a squeeze setup.

    Spec proxy by report:
      - TFF (financial futures): Asset Manager + Leveraged Money combined
      - Disaggregated (commodities): Managed Money
      - Legacy: Non-commercial

    contract: friendly key — one of SPX, NDX, VIX, 10Y, GOLD, WTI.
    """
    resolved = _resolve_contract(contract)
    if resolved is None:
        valid = ", ".join(sorted(cftc.CONTRACTS.keys()))
        return f"Unknown contract '{contract}'. Valid: {valid}"
    report_key, pattern, label = resolved
    endpoint = cftc.REPORTS[report_key]

    client = _cftc(ctx)
    resp = await client.get(endpoint, cftc.GetCotRequest(pattern))

    out = [f"## {label} — CFTC COT positioning", ""]
    out.append(resp.to_output())
    if resp.z_score is not None:
        out.append(f"Status: {_status_label(resp.z_score)}")
    return "\n".join(out)


@mcp.tool()
async def get_cot_extremes(ctx: Context) -> str:
    """Scan the curated CFTC COT universe (SPX, NDX, VIX, 10Y, Gold, WTI) and
    return a positioning table with extremity flags.

    For each contract: latest net spec positioning, 1-week change, 52-week
    z-score, percentile, and a status label. Extremes (|z| > 2) are
    contrarian signals worth weighing alongside sentiment, breadth, and IV.

    No arguments. Runs all six contracts concurrently. Reports are weekly
    (released Friday 3:30pm ET reflecting Tuesday positions).
    """
    client = _cftc(ctx)

    keys = list(cftc.CONTRACTS.keys())
    tasks = []
    for key in keys:
        report_key, pattern, _ = cftc.CONTRACTS[key]
        endpoint = cftc.REPORTS[report_key]
        tasks.append(client.get(endpoint, cftc.GetCotRequest(pattern)))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    rows: list[list[str]] = []
    warnings: list[str] = []
    latest_dates: set[str] = set()

    for key, resp in zip(keys, results, strict=True):
        _, _, label = cftc.CONTRACTS[key]
        if isinstance(resp, BaseException):
            warnings.append(_exc_summary(f"CFTC COT {key}", resp))
            rows.append([key, label, "—", "—", "—", "—", "fetch failed"])
            continue
        if resp.latest_date:
            latest_dates.add(resp.latest_date)
        net = f"{resp.latest_net:+,.0f}" if resp.latest_net is not None else "—"
        wow = f"{resp.wow_change:+,.0f}" if resp.wow_change is not None else "—"
        z = f"{resp.z_score:+.2f}" if resp.z_score is not None else "—"
        pct = f"{resp.percentile:.0f}%" if resp.percentile is not None else "—"
        rows.append([key, label, net, wow, z, pct, _status_label(resp.z_score)])

    headers = ["Key", "Contract", "Net specs", "WoW Δ", "52w z", "Pctl", "Status"]
    table = md_table(headers, rows)

    out = ["## CFTC COT — speculator positioning extremes"]
    if latest_dates:
        out.append(f"*Reports as of: {', '.join(sorted(latest_dates))}*")
    out.append("")
    if warnings:
        out.append("⚠ Some fetches failed:")
        for w in warnings:
            out.append(f"  • {w}")
        out.append("")
    out.append(table)
    out.append("")
    out.append(
        "Spec proxies: SPX/NDX/VIX/10Y = Asset Manager + Leveraged Money (TFF); "
        "Gold/WTI = Managed Money (Disaggregated). Net = long − short."
    )
    return "\n".join(out)
