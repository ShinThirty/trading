"""Catalyst tracking attached to pipeline entries.

Pipeline entry CRUD lives in `pipeline.py`.
"""

from fastmcp import Context, FastMCP
from trading_clients.table_helpers import kv_table, list_table

from trading_mcp.db.pipeline import (
    add_catalyst,
    close_catalyst,
    get_active_entry,
    list_catalysts,
    update_catalyst,
)
from trading_mcp.helpers import _db

mcp = FastMCP("pipeline-catalysts-tools")


_CATALYST_LIST_COLUMNS = ["ID", "Ticker", "Type", "Date", "Magnitude", "Description", "Status"]


def _catalyst_detail(cat: dict) -> str:
    data = {}
    for label, key in [
        ("ID", "id"),
        ("Ticker", "ticker"),
        ("Entry ID", "entry_id"),
        ("Type", "type"),
        ("Date", "date"),
        ("Magnitude", "magnitude"),
        ("Description", "description"),
        ("Status", "status"),
        ("Outcome", "outcome"),
        ("Created", "created_at"),
        ("Updated", "updated_at"),
    ]:
        val = cat.get(key)
        if val is not None:
            data[label] = val
    return kv_table(data)


def _catalysts_table(catalysts: list[dict]) -> str:
    rows = [
        {
            "ID": str(c["id"]),
            "Ticker": c.get("ticker", ""),
            "Type": c["type"],
            "Date": c.get("date") or "",
            "Magnitude": c.get("magnitude") or "",
            "Description": c.get("description") or "",
            "Status": c["status"],
        }
        for c in catalysts
    ]
    return list_table(rows, _CATALYST_LIST_COLUMNS)


@mcp.tool()
async def pipeline_catalyst_add(
    ctx: Context,
    ticker: str,
    type: str,
    date: str | None = None,
    magnitude: str | None = None,
    description: str | None = None,
) -> str:
    """Add a catalyst to a pipeline entry.

    ticker: stock symbol with an active pipeline entry.
    type: earnings, product-launch, fda, legal, macro, guidance, analyst, or other.
    date: expected date (YYYY-MM-DD).
    magnitude: expected impact — full, standard, or reduced.
    description: what the catalyst is (e.g. 'Q2 earnings report', 'FDA Phase 3 results').
    """
    conn = _db(ctx)
    entry = await get_active_entry(conn, ticker)
    if entry is None:
        return f"No active pipeline entry for {ticker.upper()}"
    data = {
        k: v
        for k, v in {
            "type": type,
            "date": date,
            "magnitude": magnitude,
            "description": description,
        }.items()
        if v is not None
    }
    cat = await add_catalyst(conn, entry["id"], data)
    cat["ticker"] = entry["ticker"]
    return _catalyst_detail(cat)


@mcp.tool()
async def pipeline_catalyst_list(
    ctx: Context,
    ticker: str | None = None,
    status: str | None = None,
    days_ahead: int | None = None,
) -> str:
    """List catalysts, optionally filtered.

    ticker: filter to a specific stock's catalysts.
    status: filter by upcoming, hit, missed, or passed.
    days_ahead: show only catalysts with dates within this many days from today.
        When used without a ticker, surfaces upcoming catalysts across the entire
        pipeline — useful for biweekly reviews and momentum screening.
    """
    conn = _db(ctx)
    entry_id = None
    if ticker:
        entry = await get_active_entry(conn, ticker)
        if entry is None:
            return f"No active pipeline entry for {ticker.upper()}"
        entry_id = entry["id"]
    catalysts = await list_catalysts(conn, entry_id=entry_id, status=status, days_ahead=days_ahead)
    if not catalysts:
        return "(no catalysts match filters)"
    return _catalysts_table(catalysts)


@mcp.tool()
async def pipeline_catalyst_update(
    ctx: Context,
    catalyst_id: int,
    type: str | None = None,
    date: str | None = None,
    magnitude: str | None = None,
    description: str | None = None,
) -> str:
    """Update a catalyst. Only provided fields are changed.

    catalyst_id: the catalyst ID (from pipeline_catalyst_list).
    """
    conn = _db(ctx)
    updates = {
        k: v
        for k, v in {
            "type": type,
            "date": date,
            "magnitude": magnitude,
            "description": description,
        }.items()
        if v is not None
    }
    cat = await update_catalyst(conn, catalyst_id, updates)
    return _catalyst_detail(cat)


@mcp.tool()
async def pipeline_catalyst_close(
    ctx: Context,
    catalyst_id: int,
    status: str = "passed",
    outcome: str | None = None,
) -> str:
    """Mark a catalyst as resolved.

    catalyst_id: the catalyst ID (from pipeline_catalyst_list).
    status: hit (catalyst played out as expected), missed (didn't materialize),
            or passed (catalyst occurred but no trade action taken).
    outcome: what actually happened (e.g. 'Beat EPS by 12%, stock gapped +8%').
    """
    conn = _db(ctx)
    cat = await close_catalyst(conn, catalyst_id, status, outcome)
    return _catalyst_detail(cat)
