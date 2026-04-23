from fastmcp import Context, FastMCP
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.db.decisions import (
    add_decision,
    close_decision,
    get_decision_by_id,
    list_decisions,
    update_decision,
)
from trading_mcp.helpers import _db

mcp = FastMCP("decision-tools")

_DETAIL_FIELDS = [
    ("ID", "id"),
    ("Ticker", "ticker"),
    ("Strike", "strike"),
    ("Expiry", "expiry"),
    ("Type", "option_type"),
    ("Account", "account"),
    ("Qty", "quantity"),
    ("Action", "action"),
    ("Status", "status"),
    ("Rationale", "rationale"),
    ("Deadline", "deadline"),
    ("Outcome", "outcome"),
    ("Source", "source"),
    ("Roll ID", "roll_id"),
    ("Created", "created_at"),
    ("Updated", "updated_at"),
    ("Completed", "completed_at"),
]

_LIST_COLUMNS = [
    "ID", "Ticker", "Strike", "Exp", "Type", "Action", "Status", "Deadline", "Source",
]


def _decision_detail(decision: dict) -> str:
    data = {}
    for label, key in _DETAIL_FIELDS:
        val = decision.get(key)
        if val is not None:
            if key == "strike":
                val = fmt_number(val, 0)
            data[label] = val
    return kv_table(data)


def _decisions_table(decisions: list[dict]) -> str:
    rows = [
        {
            "ID": str(d["id"]),
            "Ticker": d["ticker"],
            "Strike": fmt_number(d["strike"], 0),
            "Exp": d["expiry"],
            "Type": (d.get("option_type") or "")[0:1].upper(),
            "Action": d["action"],
            "Status": d["status"],
            "Deadline": d.get("deadline") or "",
            "Source": d.get("source") or "",
        }
        for d in decisions
    ]
    return list_table(rows, _LIST_COLUMNS)


@mcp.tool()
async def decision_add(
    ctx: Context,
    ticker: str,
    strike: float,
    expiry: str,
    option_type: str,
    action: str,
    account: str | None = None,
    quantity: int = 1,
    status: str = "PENDING",
    rationale: str | None = None,
    deadline: str | None = None,
    source: str | None = None,
    roll_id: int | None = None,
) -> str:
    """Record an option management decision.

    ticker: underlying symbol (e.g. 'XLK').
    strike: option strike price.
    expiry: option expiry (ISO date, e.g. '2026-05-01').
    option_type: 'call' or 'put'.
    action: CLOSE (buy back), ROLL (link via roll_id), ASSIGN (let expire ITM),
            HOLD (keep, re-evaluate later), WRITE_NEW (open a new position).
    account: account name (e.g. 'Roth IRA', 'Individual Cash').
    quantity: number of contracts (default 1).
    status: PENDING (default), DONE, EXPIRED, CANCELLED.
    rationale: why this decision was made.
    deadline: by when to execute (ISO date).
    source: where the decision came from (e.g. 'briefing', 'review', 'roll').
    roll_id: link to a roll entry if action is ROLL.
    """
    conn = _db(ctx)
    data = {
        k: v
        for k, v in {
            "ticker": ticker,
            "strike": strike,
            "expiry": expiry,
            "option_type": option_type,
            "action": action,
            "account": account,
            "quantity": quantity,
            "status": status,
            "rationale": rationale,
            "deadline": deadline,
            "source": source,
            "roll_id": roll_id,
        }.items()
        if v is not None
    }
    decision = await add_decision(conn, data)
    return _decision_detail(decision)


@mcp.tool()
async def decision_list(
    ctx: Context,
    ticker: str | None = None,
    status: str | None = None,
    action: str | None = None,
    account: str | None = None,
    option_type: str | None = None,
    include_closed: bool = False,
) -> str:
    """List option decisions with optional filters.

    ticker: filter by underlying symbol.
    status: filter by status (PENDING, DONE, etc.).
    action: filter by action (CLOSE, ROLL, ASSIGN, HOLD, WRITE_NEW).
    account: filter by account name.
    option_type: filter by 'call' or 'put'.
    include_closed: include terminal entries (default false).
    """
    conn = _db(ctx)
    decisions = await list_decisions(
        conn,
        ticker=ticker,
        status=status,
        action=action,
        account=account,
        option_type=option_type,
        include_closed=include_closed,
    )
    if not decisions:
        return "(no decisions match filters)"
    return _decisions_table(decisions)


@mcp.tool()
async def decision_get(ctx: Context, decision_id: int) -> str:
    """Get details for a specific decision by ID."""
    conn = _db(ctx)
    decision = await get_decision_by_id(conn, decision_id)
    if decision is None:
        return f"No decision with id {decision_id}"
    return _decision_detail(decision)


@mcp.tool()
async def decision_update(
    ctx: Context,
    decision_id: int,
    strike: float | None = None,
    expiry: str | None = None,
    option_type: str | None = None,
    action: str | None = None,
    status: str | None = None,
    account: str | None = None,
    quantity: int | None = None,
    rationale: str | None = None,
    deadline: str | None = None,
    source: str | None = None,
    roll_id: int | None = None,
) -> str:
    """Update a pending decision. Only provided fields are changed.

    decision_id: the decision to update.
    """
    conn = _db(ctx)
    updates = {
        k: v
        for k, v in {
            "strike": strike,
            "expiry": expiry,
            "option_type": option_type,
            "action": action,
            "status": status,
            "account": account,
            "quantity": quantity,
            "rationale": rationale,
            "deadline": deadline,
            "source": source,
            "roll_id": roll_id,
        }.items()
        if v is not None
    }
    decision = await update_decision(conn, decision_id, updates)
    return _decision_detail(decision)


@mcp.tool()
async def decision_close(
    ctx: Context,
    decision_id: int,
    status: str = "DONE",
    outcome: str | None = None,
) -> str:
    """Close a decision (terminal state).

    decision_id: the decision to close.
    status: DONE (default), EXPIRED, or CANCELLED.
    outcome: optional note on what happened.
    """
    conn = _db(ctx)
    decision = await close_decision(conn, decision_id, status, outcome=outcome)
    return _decision_detail(decision)
