"""TSMC monthly revenue tool.

TSMC publishes consolidated monthly revenue (NT$ millions) on the 10th of each
month — a clean leading indicator for the global semi cycle. Sourced from the
TWSE OpenAPI t187ap05_L feed (TSMC's own IR page is now Cloudflare-gated and
unscrapable). The feed only exposes the most recent reporting month, so we
accumulate history in the local SQLite DB across calls.

Returns trailing-N months sorted most-recent first with revenue (NT$M as
reported by TSMC), YoY% (as reported), and MoM% (computed locally from
consecutive DB rows), plus a freshness flag and a "rows available" note so
the caller knows when history is still warming up.
"""

from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import twse
from trading_clients.table_helpers import md_table

from trading_mcp.db import twse_revenue
from trading_mcp.helpers import _db, _exc_summary, _twse

mcp = FastMCP("tsmc-tools")

TSMC_COMPANY_CODE = "2330"


@mcp.tool()
async def get_tsmc_monthly_revenue(ctx: Context, months: int = 13) -> str:
    """Get TSMC's consolidated monthly revenue for the trailing N months.

    Returns a markdown table sorted most-recent first with revenue (NT$
    millions, as reported by TSMC), YoY% (as reported), and MoM% (computed
    from prior-month revenue). Released on the 10th of each month — surfaces
    a "freshness" line indicating whether the latest reported month is the
    prior calendar month (fresh print) or older (still awaiting).

    Data flows TWSE OpenAPI → local SQLite cache → output. Each call upserts
    the headline month plus the prior-month and same-month-prior-year anchors
    that the feed carries, so history accumulates naturally over time.

    months: number of trailing months to surface, default 13 so 12 MoM deltas
    plus a YoY anchor are visible. Caps to whatever the DB actually has.

    TSMC is the foundry layer underneath every advanced AI accelerator
    (NVDA Blackwell/Rubin, AMD MI3xx, AVGO ASIC, MRVL custom silicon) so a
    YoY surprise on release morning often pre-prints upside in the broader
    semi tape before any of those names report.
    """
    if months < 1:
        return "months must be >= 1"

    db = _db(ctx)
    client = _twse(ctx)

    fetch_warning: str | None = None
    try:
        feed: twse.ListedMonthlyRevenueResponse = await client.get(
            twse.LISTED_MONTHLY_REVENUE, twse.ListedMonthlyRevenueRequest()
        )
        row = feed.by_code(TSMC_COMPANY_CODE)
        if row is not None:
            await _persist_openapi_row(db, row)
        else:
            fetch_warning = (
                f"⚠️ TSMC ({TSMC_COMPANY_CODE}) not present in TWSE OpenAPI feed "
                f"({len(feed.rows)} companies); returning DB cache only"
            )
    except Exception as exc:  # noqa: BLE001 — degrade to DB cache
        fetch_warning = (
            f"⚠️ TWSE OpenAPI fetch failed ({_exc_summary('twse', exc)}); returning DB cache only"
        )

    cached = await twse_revenue.select_recent(db, TSMC_COMPANY_CODE, months + 1)
    if not cached:
        msg = (
            "(no TSMC revenue data cached yet — run the prepopulate script "
            "or wait for the next OpenAPI poll)"
        )
        if fetch_warning:
            return f"{fetch_warning}\n\n{msg}"
        return msg

    chronological = list(reversed(cached))  # oldest → newest for MoM
    revenue_by_ym: dict[tuple[int, int], int] = {
        (r["year"], r["month"]): r["revenue_thousands"] for r in chronological
    }

    table_rows: list[list[str]] = []
    for r in cached[:months]:
        y, m = r["year"], r["month"]
        prev_year = y if m > 1 else y - 1
        prev_month = m - 1 if m > 1 else 12
        prev_rev = revenue_by_ym.get((prev_year, prev_month))
        if prev_rev and r["revenue_thousands"] and prev_rev != 0:
            mom = (r["revenue_thousands"] / prev_rev - 1.0) * 100
            mom_str = f"{mom:+.1f}%"
        else:
            mom_str = "—"
        # Display revenue in NT$ millions (feed is in thousands).
        rev_millions = r["revenue_thousands"] / 1000
        yoy_str = f"{r['yoy_pct']:+.1f}%" if r["yoy_pct"] is not None else "—"
        table_rows.append([f"{y}-{m:02d}", f"{rev_millions:,.0f}", yoy_str, mom_str])

    table = md_table(["Month", "Revenue (NT$M)", "YoY", "MoM"], table_rows)

    today = date.today()
    prior_cal_year = today.year if today.month > 1 else today.year - 1
    prior_cal_month = today.month - 1 if today.month > 1 else 12
    latest = cached[0]
    if (latest["year"], latest["month"]) == (prior_cal_year, prior_cal_month):
        freshness = (
            f"✅ Latest print {latest['year']}-{latest['month']:02d} is the prior calendar month "
            f"(released ~10th of {today.year}-{today.month:02d})"
        )
    else:
        freshness = (
            f"⏰ Latest print is {latest['year']}-{latest['month']:02d}; "
            f"awaiting {prior_cal_year}-{prior_cal_month:02d} release "
            f"(typically published around the 10th)"
        )

    total_rows = await twse_revenue.count(db, TSMC_COMPANY_CODE)
    coverage = f"(DB has {total_rows} months total; showing {min(months, len(cached))})"

    parts = ["## TSMC consolidated monthly revenue"]
    if fetch_warning:
        parts.append("")
        parts.append(fetch_warning)
    parts.extend(["", freshness, coverage, "", table])
    return "\n".join(parts)


async def _persist_openapi_row(db, row: twse.MonthlyRevenueRow) -> None:
    """Upsert every revenue data point carried in a single OpenAPI row.

    From the headline row for (year, month) we get four to five months of
    coverage in a single call:
      - (year, month)      headline revenue + yoy_pct
      - (year, month - 1)  prior-month revenue (no metrics; metrics from prior poll)
      - (year - 1, month)  same-month-prior-year (no metrics for our purposes)
      - (year, 1)          derivable when month ∈ {2, 3} via YTD arithmetic
      - (year, 2)          derivable when month == 3 (prior_month gives Feb directly)
    """
    code = row.company_code
    y, m = row.year, row.month

    # Headline month — full metrics.
    await twse_revenue.upsert(
        db,
        company_code=code,
        year=y,
        month=m,
        revenue_thousands=row.revenue_curr_thousands,
        yoy_pct=row.yoy_pct,
        source="twse_openapi",
    )

    # Prior month — revenue only, no metrics in this row.
    if row.revenue_prior_thousands is not None:
        prev_y = y if m > 1 else y - 1
        prev_m = m - 1 if m > 1 else 12
        await twse_revenue.upsert(
            db,
            company_code=code,
            year=prev_y,
            month=prev_m,
            revenue_thousands=row.revenue_prior_thousands,
            yoy_pct=None,
            source="twse_openapi",
        )

    # Same-month-prior-year anchor.
    if row.revenue_lastyear_thousands is not None:
        await twse_revenue.upsert(
            db,
            company_code=code,
            year=y - 1,
            month=m,
            revenue_thousands=row.revenue_lastyear_thousands,
            yoy_pct=None,
            source="twse_openapi",
        )

    # YTD arithmetic: when the current month is February or March, we can
    # derive January's revenue (and Feb's, when March is current) from the
    # YTD field. Beyond March there are too many unknowns to solve in one row.
    if row.ytd_revenue_thousands is None:
        return
    if m == 2:
        jan = row.ytd_revenue_thousands - row.revenue_curr_thousands
        if jan > 0:
            await twse_revenue.upsert(
                db,
                company_code=code,
                year=y,
                month=1,
                revenue_thousands=jan,
                yoy_pct=None,
                source="derived",
            )
    elif m == 3 and row.revenue_prior_thousands is not None:
        jan = row.ytd_revenue_thousands - row.revenue_curr_thousands - row.revenue_prior_thousands
        if jan > 0:
            await twse_revenue.upsert(
                db,
                company_code=code,
                year=y,
                month=1,
                revenue_thousands=jan,
                yoy_pct=None,
                source="derived",
            )


__all__ = ["mcp", "get_tsmc_monthly_revenue"]
