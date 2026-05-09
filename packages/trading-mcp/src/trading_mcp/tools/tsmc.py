"""TSMC monthly revenue tool.

TSMC publishes consolidated monthly revenue (NT$ millions) on the 10th of each
month — a clean leading indicator for the global semi cycle. The tool returns
trailing-N months ordered most-recent first, with YoY% (from TSMC) and MoM%
(computed locally) on each row, plus a freshness flag if the latest reported
month is the prior calendar month (post-print) vs older (still awaiting).
"""

from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import tsmc
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _tsmc

mcp = FastMCP("tsmc-tools")


@mcp.tool()
async def get_tsmc_monthly_revenue(ctx: Context, months: int = 13) -> str:
    """Get TSMC's consolidated monthly revenue for the trailing N months.

    Returns a markdown table sorted most-recent first with revenue (NT$
    millions, as reported by TSMC), YoY% (as reported), and MoM% (computed
    from prior-month revenue). Released on the 10th of each month — surfaces
    a "freshness" line indicating whether the latest reported month is the
    prior calendar month (fresh print) or older (still awaiting).

    months: number of trailing months to surface, default 13 so 12 MoM deltas
    plus a YoY anchor are visible. Caps to whatever the table actually has.

    TSMC is the foundry layer underneath every advanced AI accelerator
    (NVDA Blackwell/Rubin, AMD MI3xx, AVGO ASIC, MRVL custom silicon) so a
    YoY surprise on release morning often pre-prints upside in the broader
    semi tape before any of those names report.
    """
    if months < 1:
        return "months must be >= 1"

    client = _tsmc(ctx)
    today = date.today()
    current_year = today.year

    # Fetch current year. If we need more rows than the current year has
    # actually reported, pull prior year too. (Fetching prior year is almost
    # always required at any time of year if months >= 13.)
    current = await client.get(tsmc.MONTHLY_REVENUE, tsmc.GetMonthlyRevenueRequest(current_year))
    reported_current = [r for r in current.rows if r.revenue_ntd_m is not None]

    rows: list[tsmc.MonthlyRevenue] = list(reported_current)
    if len(rows) < months:
        prior = await client.get(
            tsmc.MONTHLY_REVENUE, tsmc.GetMonthlyRevenueRequest(current_year - 1)
        )
        rows = [r for r in prior.rows if r.revenue_ntd_m is not None] + rows

    # If the user asked for an even longer window, walk back further.
    while len(rows) < months and rows:
        oldest_year = rows[0].year
        if oldest_year < current_year - 5:  # safety stop — page only goes to 1999
            break
        older = await client.get(
            tsmc.MONTHLY_REVENUE, tsmc.GetMonthlyRevenueRequest(oldest_year - 1)
        )
        rows = [r for r in older.rows if r.revenue_ntd_m is not None] + rows

    # Slice to trailing N (chronological order preserved for MoM computation).
    rows.sort(key=lambda r: (r.year, r.month))
    rows = rows[-months:]

    # Compute MoM. Need the immediately-prior reported month, even if it's
    # outside the requested window — pull it on demand if we sliced it off.
    mom: dict[tuple[int, int], float | None] = {}
    revenue_map: dict[tuple[int, int], float] = {
        (r.year, r.month): r.revenue_ntd_m  # type: ignore[misc]
        for r in rows
        if r.revenue_ntd_m is not None
    }
    # Hydrate prior-month context for the oldest row if it's missing
    if rows:
        first = rows[0]
        prev_year = first.year if first.month > 1 else first.year - 1
        prev_month = first.month - 1 if first.month > 1 else 12
        if (prev_year, prev_month) not in revenue_map and prev_year >= current_year - 5:
            extra = await client.get(tsmc.MONTHLY_REVENUE, tsmc.GetMonthlyRevenueRequest(prev_year))
            for r in extra.rows:
                if r.revenue_ntd_m is not None:
                    revenue_map.setdefault((r.year, r.month), r.revenue_ntd_m)

    for r in rows:
        prev_year = r.year if r.month > 1 else r.year - 1
        prev_month = r.month - 1 if r.month > 1 else 12
        prev_rev = revenue_map.get((prev_year, prev_month))
        if prev_rev and r.revenue_ntd_m is not None and prev_rev != 0:
            mom[(r.year, r.month)] = (r.revenue_ntd_m / prev_rev - 1.0) * 100
        else:
            mom[(r.year, r.month)] = None

    # Build output, most-recent first.
    rows_desc = list(reversed(rows))
    table_rows: list[list[str]] = []
    for r in rows_desc:
        m = mom.get((r.year, r.month))
        table_rows.append(
            [
                f"{r.year}-{r.month:02d}",
                f"{r.revenue_ntd_m:,.0f}" if r.revenue_ntd_m is not None else "—",
                f"{r.yoy_pct:+.1f}%" if r.yoy_pct is not None else "—",
                f"{m:+.1f}%" if m is not None else "—",
            ]
        )
    table = md_table(["Month", "Revenue (NT$M)", "YoY", "MoM"], table_rows)

    # Freshness: TSMC reports prior-month revenue around the 10th. If the
    # latest reported row is the immediately-prior calendar month, the print
    # is fresh; if older, we're between prints (and approaching the 10th of
    # the next release cycle, the new print is overdue).
    latest = rows[-1]
    prior_calendar_year = today.year if today.month > 1 else today.year - 1
    prior_calendar_month = today.month - 1 if today.month > 1 else 12
    if (latest.year, latest.month) == (prior_calendar_year, prior_calendar_month):
        freshness = (
            f"✅ Latest print {latest.year}-{latest.month:02d} is the prior calendar month "
            f"(released ~10th of {today.year}-{today.month:02d})"
        )
    else:
        freshness = (
            f"⏰ Latest print is {latest.year}-{latest.month:02d}; "
            f"awaiting {prior_calendar_year}-{prior_calendar_month:02d} release "
            f"(typically published around the 10th)"
        )

    out = ["## TSMC consolidated monthly revenue", "", freshness, "", table]
    return "\n".join(out)


__all__ = ["mcp", "get_tsmc_monthly_revenue"]
