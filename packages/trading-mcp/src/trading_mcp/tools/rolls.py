from fastmcp import Context, FastMCP
from trading_clients.table_helpers import fmt_number, kv_table, list_table

from trading_mcp.db.rolls import (
    add_roll,
    close_roll,
    get_roll_by_id,
    list_rolls,
    update_roll,
)
from trading_mcp.helpers import _db

mcp = FastMCP("roll-tools")

_DETAIL_FIELDS = [
    ("ID", "id"),
    ("Ticker", "ticker"),
    ("Account", "account"),
    ("Type", "option_type"),
    ("Qty", "quantity"),
    ("From Strike", "from_strike"),
    ("From Expiry", "from_expiry"),
    ("To Strike", "to_strike"),
    ("To Expiry", "to_expiry"),
    ("Status", "status"),
    ("Net Credit", "net_credit"),
    ("Reason", "reason"),
    ("Created", "created_at"),
    ("Updated", "updated_at"),
    ("Filled", "filled_at"),
]

_LIST_COLUMNS = [
    "ID", "Ticker", "Account", "Type", "Qty", "From", "To", "Status", "Credit",
]


def _roll_detail(roll: dict) -> str:
    data = {}
    for label, key in _DETAIL_FIELDS:
        val = roll.get(key)
        if val is not None:
            if key in ("from_strike", "to_strike"):
                val = fmt_number(val, 0)
            elif key == "net_credit":
                val = fmt_number(val, 2)
            data[label] = val
    return kv_table(data)


def _fmt_leg(strike: float | None, expiry: str | None, opt_type: str | None) -> str:
    if strike is None or expiry is None:
        return "—"
    suffix = "C" if opt_type == "call" else "P"
    return f"${fmt_number(strike, 0)}{suffix} {expiry}"


def _rolls_table(rolls: list[dict]) -> str:
    rows = [
        {
            "ID": str(r["id"]),
            "Ticker": r["ticker"],
            "Account": r.get("account") or "",
            "Type": (r.get("option_type") or "")[0:1].upper(),
            "Qty": str(r.get("quantity") or 1),
            "From": _fmt_leg(r.get("from_strike"), r.get("from_expiry"), r.get("option_type")),
            "To": _fmt_leg(r.get("to_strike"), r.get("to_expiry"), r.get("option_type")),
            "Status": r["status"],
            "Credit": fmt_number(r["net_credit"], 2) if r.get("net_credit") is not None else "",
        }
        for r in rolls
    ]
    return list_table(rows, _LIST_COLUMNS)


@mcp.tool()
async def roll_add(
    ctx: Context,
    ticker: str,
    option_type: str,
    from_strike: float,
    from_expiry: str,
    to_strike: float | None = None,
    to_expiry: str | None = None,
    status: str = "PLANNED",
    account: str | None = None,
    quantity: int = 1,
    net_credit: float | None = None,
    reason: str | None = None,
) -> str:
    """Add a new option roll entry.

    ticker: underlying symbol (e.g. 'SMH').
    option_type: 'call' or 'put'.
    from_strike: current option strike price.
    from_expiry: current option expiry (ISO date, e.g. '2026-05-01').
    to_strike: new strike (omit if not rolling / SKIP / EXPIRED).
    to_expiry: new expiry (omit if not rolling).
    status: PLANNED (default), WORKING, FILLED, EXPIRED, CANCELLED, SKIP.
    account: account name (e.g. 'Individual Cash', 'Roth IRA').
    quantity: number of contracts (default 1).
    net_credit: net credit received (positive) or debit paid (negative).
    reason: why rolling or why not.
    """
    conn = _db(ctx)
    data = {
        k: v
        for k, v in {
            "ticker": ticker,
            "option_type": option_type,
            "from_strike": from_strike,
            "from_expiry": from_expiry,
            "to_strike": to_strike,
            "to_expiry": to_expiry,
            "status": status,
            "account": account,
            "quantity": quantity,
            "net_credit": net_credit,
            "reason": reason,
        }.items()
        if v is not None
    }
    roll = await add_roll(conn, data)
    return _roll_detail(roll)


@mcp.tool()
async def roll_list(
    ctx: Context,
    ticker: str | None = None,
    status: str | None = None,
    account: str | None = None,
    option_type: str | None = None,
    include_closed: bool = False,
) -> str:
    """List option roll entries with optional filters.

    ticker: filter by underlying symbol.
    status: filter by status (PLANNED, WORKING, FILLED, etc.).
    account: filter by account name.
    option_type: filter by 'call' or 'put'.
    include_closed: include terminal entries (default false).
    """
    conn = _db(ctx)
    rolls = await list_rolls(
        conn,
        ticker=ticker,
        status=status,
        account=account,
        option_type=option_type,
        include_closed=include_closed,
    )
    if not rolls:
        return "(no rolls match filters)"
    return _rolls_table(rolls)


@mcp.tool()
async def roll_get(ctx: Context, roll_id: int) -> str:
    """Get details for a specific roll by ID."""
    conn = _db(ctx)
    roll = await get_roll_by_id(conn, roll_id)
    if roll is None:
        return f"No roll with id {roll_id}"
    return _roll_detail(roll)


@mcp.tool()
async def roll_update(
    ctx: Context,
    roll_id: int,
    to_strike: float | None = None,
    to_expiry: str | None = None,
    status: str | None = None,
    account: str | None = None,
    quantity: int | None = None,
    net_credit: float | None = None,
    reason: str | None = None,
) -> str:
    """Update an active roll entry. Only provided fields are changed.

    roll_id: the roll to update.
    """
    conn = _db(ctx)
    updates = {
        k: v
        for k, v in {
            "to_strike": to_strike,
            "to_expiry": to_expiry,
            "status": status,
            "account": account,
            "quantity": quantity,
            "net_credit": net_credit,
            "reason": reason,
        }.items()
        if v is not None
    }
    roll = await update_roll(conn, roll_id, updates)
    return _roll_detail(roll)


@mcp.tool()
async def roll_close(
    ctx: Context,
    roll_id: int,
    status: str = "FILLED",
    reason: str | None = None,
    net_credit: float | None = None,
) -> str:
    """Close a roll entry (terminal state).

    roll_id: the roll to close.
    status: FILLED (default), EXPIRED, CANCELLED, or SKIP.
    reason: optional note explaining the outcome.
    net_credit: net credit received (positive) or debit paid (negative).
    """
    conn = _db(ctx)
    roll = await close_roll(conn, roll_id, status, reason=reason, net_credit=net_credit)
    return _roll_detail(roll)
