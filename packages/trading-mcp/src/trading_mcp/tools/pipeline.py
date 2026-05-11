"""Pipeline entry tracking — add/update/get/list/note/close.

Catalysts live in `pipeline_catalysts.py`. Cross-stock comparison tools
(`compare_credit_efficiency`, `compare_debit_efficiency`) live in
`comparison.py`.
"""

from fastmcp import Context, FastMCP
from trading_clients.table_helpers import kv_table, list_table

from trading_mcp.db.pipeline import (
    add_entry,
    add_note,
    close_entry,
    get_active_entry,
    get_notes,
    list_entries,
    update_entry,
)
from trading_mcp.helpers import _db
from trading_mcp.pipeline_sync import publish_pipeline_to_s3

mcp = FastMCP("pipeline-tools")


_DETAIL_FIELDS = [
    ("Ticker", "ticker"),
    ("Intent", "intent"),
    ("Status", "status"),
    ("Pipeline", "pipeline"),
    ("Account", "account"),
    ("Tier", "tier"),
    ("Conviction", "conviction"),
    ("Priority", "priority"),
    ("P/E", "pe"),
    ("PEG", "peg"),
    ("ROE %", "roe"),
    ("D/E", "de"),
    ("Drawdown %", "drawdown_pct"),
    ("Rev Growth %", "rev_growth"),
    ("Earnings Date", "earnings_date"),
    ("Thesis", "thesis"),
    ("Position", "position"),
    ("Entry Plan", "entry_plan"),
    ("Management", "management"),
    ("Catalysts", "catalysts"),
    ("Watch Items", "watch_items"),
    ("Created", "created_at"),
    ("Updated", "updated_at"),
    ("Closed", "closed_at"),
]

_LIST_COLUMNS = [
    "Ticker",
    "Intent",
    "Status",
    "Pipeline",
    "Tier",
    "Conviction",
    "Priority",
    "Earnings",
]


def _entry_detail(entry: dict) -> str:
    data = {}
    for label, key in _DETAIL_FIELDS:
        val = entry.get(key)
        if val is not None:
            data[label] = val
    return kv_table(data)


def _entries_table(entries: list[dict]) -> str:
    rows = [
        {
            "Ticker": e["ticker"],
            "Intent": e["intent"],
            "Status": e["status"],
            "Pipeline": e.get("pipeline") or "",
            "Tier": e.get("tier") or "",
            "Conviction": e.get("conviction") or "",
            "Priority": str(e["priority"]) if e.get("priority") is not None else "",
            "Earnings": e.get("earnings_date") or "",
        }
        for e in entries
    ]
    return list_table(rows, _LIST_COLUMNS)


@mcp.tool()
async def pipeline_add(
    ctx: Context,
    ticker: str,
    intent: str,
    status: str = "PIPELINE",
    pipeline: str | None = None,
    account: str | None = None,
    tier: str | None = None,
    conviction: str | None = None,
    priority: int | None = None,
    thesis: str | None = None,
    position: str | None = None,
    entry_plan: str | None = None,
    management: str | None = None,
    catalysts: str | None = None,
    watch_items: str | None = None,
    pe: float | None = None,
    peg: float | None = None,
    roe: float | None = None,
    de: float | None = None,
    drawdown_pct: float | None = None,
    rev_growth: float | None = None,
    earnings_date: str | None = None,
) -> str:
    """Add a new ticker to the trading pipeline.

    ticker: stock symbol (e.g. 'ADBE').
    intent: accumulate, enter-at-discount, harvest-premium, bearish, exit,
            ipo-momentum, or watchlist.
    status: LIVE, WAITING, PIPELINE (default), SKIP, CLOSED, SHELVED, REMOVED.
    pipeline: webull or fidelity.
    tier: full, standard, or reduced.
    conviction: highest, high, moderate, low, or negative.
    priority: integer ordering within a pipeline (1 = top).
    Numeric fields (pe, peg, roe, de, drawdown_pct, rev_growth) are point-in-time
    snapshots at the time of the pipeline decision.
    """
    conn = _db(ctx)
    data = {
        k: v
        for k, v in {
            "ticker": ticker,
            "intent": intent,
            "status": status,
            "pipeline": pipeline,
            "account": account,
            "tier": tier,
            "conviction": conviction,
            "priority": priority,
            "thesis": thesis,
            "position": position,
            "entry_plan": entry_plan,
            "management": management,
            "catalysts": catalysts,
            "watch_items": watch_items,
            "pe": pe,
            "peg": peg,
            "roe": roe,
            "de": de,
            "drawdown_pct": drawdown_pct,
            "rev_growth": rev_growth,
            "earnings_date": earnings_date,
        }.items()
        if v is not None
    }
    entry = await add_entry(conn, data)
    await publish_pipeline_to_s3(conn)
    return _entry_detail(entry)


@mcp.tool()
async def pipeline_update(
    ctx: Context,
    ticker: str,
    intent: str | None = None,
    status: str | None = None,
    pipeline: str | None = None,
    account: str | None = None,
    tier: str | None = None,
    conviction: str | None = None,
    priority: int | None = None,
    thesis: str | None = None,
    position: str | None = None,
    entry_plan: str | None = None,
    management: str | None = None,
    catalysts: str | None = None,
    watch_items: str | None = None,
    pe: float | None = None,
    peg: float | None = None,
    roe: float | None = None,
    de: float | None = None,
    drawdown_pct: float | None = None,
    rev_growth: float | None = None,
    earnings_date: str | None = None,
) -> str:
    """Update an existing pipeline entry. Only provided fields are changed.

    ticker: the stock to update (must have an active entry).
    All other parameters are optional — only non-None values are applied.
    """
    conn = _db(ctx)
    updates = {
        k: v
        for k, v in {
            "intent": intent,
            "status": status,
            "pipeline": pipeline,
            "account": account,
            "tier": tier,
            "conviction": conviction,
            "priority": priority,
            "thesis": thesis,
            "position": position,
            "entry_plan": entry_plan,
            "management": management,
            "catalysts": catalysts,
            "watch_items": watch_items,
            "pe": pe,
            "peg": peg,
            "roe": roe,
            "de": de,
            "drawdown_pct": drawdown_pct,
            "rev_growth": rev_growth,
            "earnings_date": earnings_date,
        }.items()
        if v is not None
    }
    entry = await update_entry(conn, ticker, updates)
    await publish_pipeline_to_s3(conn)
    return _entry_detail(entry)


@mcp.tool()
async def pipeline_get(ctx: Context, ticker: str) -> str:
    """Get the active pipeline entry and notes for a ticker."""
    conn = _db(ctx)
    entry = await get_active_entry(conn, ticker)
    if entry is None:
        return f"No active pipeline entry for {ticker.upper()}"
    out = _entry_detail(entry)
    notes = await get_notes(conn, entry["id"])
    if notes:
        note_rows = [{"Date": n["created_at"], "Note": n["note"]} for n in notes]
        out += "\n\n**Notes:**\n" + list_table(note_rows, ["Date", "Note"])
    return out


@mcp.tool()
async def pipeline_list(
    ctx: Context,
    pipeline: str | None = None,
    status: str | None = None,
    intent: str | None = None,
    include_closed: bool = False,
) -> str:
    """List pipeline entries with optional filters.

    pipeline: filter by 'webull' or 'fidelity'.
    status: filter by status (LIVE, WAITING, PIPELINE, etc.).
    intent: filter by intent (accumulate, bearish, etc.).
    include_closed: include CLOSED/SHELVED/REMOVED/SKIP entries (default false).
    """
    conn = _db(ctx)
    entries = await list_entries(
        conn, pipeline=pipeline, status=status, intent=intent, include_closed=include_closed
    )
    if not entries:
        return "(no pipeline entries match filters)"
    return _entries_table(entries)


@mcp.tool()
async def pipeline_note(ctx: Context, ticker: str, note: str) -> str:
    """Append a timestamped note to a pipeline entry.

    ticker: stock symbol with an active pipeline entry.
    note: free-text note to append.
    """
    conn = _db(ctx)
    result = await add_note(conn, ticker, note)
    return f"Note added to {ticker.upper()} at {result['created_at']}"


@mcp.tool()
async def pipeline_close(
    ctx: Context,
    ticker: str,
    status: str = "CLOSED",
    reason: str | None = None,
) -> str:
    """Close a pipeline entry (terminal state).

    ticker: stock symbol to close.
    status: CLOSED (default), SHELVED, REMOVED, or SKIP.
    reason: optional note explaining why.
    """
    conn = _db(ctx)
    if reason:
        await add_note(conn, ticker, f"Closed ({status}): {reason}")
    entry = await close_entry(conn, ticker, status)
    await publish_pipeline_to_s3(conn)
    return _entry_detail(entry)


@mcp.tool()
async def pipeline_resync(ctx: Context) -> str:
    """Re-publish the active pipeline snapshot to S3.

    Use after manual SQLite edits or to recover from a sync that failed
    silently. No-ops with a clear message if PIPELINE_STATE_BUCKET /
    PIPELINE_STATE_KEY env vars are unset.
    """
    import os

    from trading_mcp.pipeline_sync import _BUCKET_ENV, _KEY_ENV

    bucket = os.environ.get(_BUCKET_ENV)
    key = os.environ.get(_KEY_ENV)
    if not bucket or not key:
        return f"Skipped — {_BUCKET_ENV} / {_KEY_ENV} not set; pipeline sync is disabled."
    conn = _db(ctx)
    count = await publish_pipeline_to_s3(conn)
    return f"Published {count} active entries to s3://{bucket}/{key}"
