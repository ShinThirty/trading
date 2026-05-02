import asyncio
from dataclasses import dataclass
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_number, kv_table, list_table, to_float
from trading_clients.tradier_client import TradierClient

from trading_mcp.db.pipeline import (
    add_catalyst,
    add_entry,
    add_note,
    close_catalyst,
    close_entry,
    get_active_entry,
    get_notes,
    list_catalysts,
    list_entries,
    update_catalyst,
    update_entry,
)
from trading_mcp.helpers import _db, _tradier

mcp = FastMCP("pipeline-tools")


@dataclass
class _OptionMatch:
    symbol: str
    stock_price: float
    strike: float
    exp: str
    dte: int
    delta: float
    bid: float
    ask: float
    mid: float


async def _gather_option_matches(
    tradier: TradierClient,
    tickers: list[str],
    opt_type: str,
    target_delta: float,
    min_dte: int,
    max_dte: int,
) -> tuple[list[_OptionMatch], list[str]]:
    today = date.today()
    mid_dte = (min_dte + max_dte) / 2

    results = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(",".join(tickers), greeks=False)),
        *[tradier.get(t.EXPIRATIONS, t.GetExpirationsRequest(sym)) for sym in tickers],
        return_exceptions=True,
    )

    quote_resp = results[0]
    if isinstance(quote_resp, BaseException):
        return [], tickers

    prices: dict[str, float] = {}
    for q in quote_resp.quotes:
        sym = q.get("symbol", "")
        last = to_float(q.get("last"))
        if sym and last:
            prices[sym] = last

    selected: dict[str, tuple[str, int]] = {}
    for i, sym in enumerate(tickers):
        exp_resp = results[i + 1]
        if isinstance(exp_resp, BaseException) or not exp_resp.dates:
            continue
        best_exp = None
        best_score = float("inf")
        for d_str in exp_resp.dates:
            dte = (date.fromisoformat(d_str) - today).days
            if dte < 1:
                continue
            in_window = min_dte <= dte <= max_dte
            score = abs(dte - mid_dte) if in_window else 1000 + abs(dte - mid_dte)
            if score < best_score:
                best_score = score
                best_exp = d_str
        if best_exp:
            selected[sym] = (best_exp, (date.fromisoformat(best_exp) - today).days)

    chain_syms = [sym for sym in tickers if sym in selected and sym in prices]
    if not chain_syms:
        return [], tickers

    chain_results = await asyncio.gather(
        *[
            tradier.get(t.CHAIN, t.GetChainRequest(sym, selected[sym][0], greeks=True))
            for sym in chain_syms
        ],
        return_exceptions=True,
    )

    matches: list[_OptionMatch] = []
    skipped: list[str] = []
    for sym, chain_resp in zip(chain_syms, chain_results):
        if isinstance(chain_resp, BaseException) or not chain_resp.options:
            skipped.append(sym)
            continue

        options = [
            o
            for o in chain_resp.options
            if o.get("option_type") == opt_type and (to_float(o.get("bid")) or 0) > 0
        ]
        if not options:
            skipped.append(sym)
            continue

        best_opt = None
        best_dist = float("inf")
        for o in options:
            greeks_d = o.get("greeks") or {}
            delta = to_float(greeks_d.get("delta"))
            if delta is None:
                continue
            dist = abs(abs(delta) - target_delta)
            if dist < best_dist:
                best_dist = dist
                best_opt = o

        if not best_opt:
            skipped.append(sym)
            continue

        bid = to_float(best_opt.get("bid")) or 0
        ask = to_float(best_opt.get("ask")) or 0
        strike = to_float(best_opt.get("strike")) or 0
        delta = to_float((best_opt.get("greeks") or {}).get("delta")) or 0
        mid = (bid + ask) / 2

        if mid <= 0 or strike <= 0:
            skipped.append(sym)
            continue

        exp_str, dte = selected[sym]
        matches.append(
            _OptionMatch(
                symbol=sym,
                stock_price=prices[sym],
                strike=strike,
                exp=exp_str,
                dte=dte,
                delta=delta,
                bid=bid,
                ask=ask,
                mid=mid,
            )
        )

    skipped.extend(sym for sym in tickers if sym not in prices and sym not in skipped)
    return matches, skipped


@mcp.tool()
async def compare_credit_efficiency(
    ctx: Context,
    symbols: str,
    option_type: str = "put",
    target_delta: float = 0.25,
    min_dte: int = 30,
    max_dte: int = 45,
) -> str:
    """Compare credit strategy premium efficiency across multiple stocks to
    prioritize capital allocation when conviction is similar.

    Finds the option closest to target_delta for each symbol and computes:
    - Annualized Yield: premium collected / capital at risk, annualized by DTE.
      Uses bid price (conservative — what you'd actually collect). Capital at
      risk = strike (puts/CSPs) or stock price (calls/CCs). Higher = richer.
    - Cushion/Yield: OTM distance (%) per unit of annualized yield. Higher = more
      margin of safety per unit of return.
    - Spread: bid/ask spread as % of mid price (informational — already reflected
      in the yield via bid pricing).

    symbols: comma-separated tickers (e.g. 'MU,ADBE,NVDA,LRCX').
    option_type: 'put' for CSPs (default), 'call' for covered calls.
    target_delta: absolute delta to target (default 0.25).
    min_dte: minimum days to expiration (default 30).
    max_dte: maximum days to expiration (default 45).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        return "(no symbols provided)"
    opt_type = option_type.lower()
    if opt_type not in ("put", "call"):
        return "(option_type must be 'put' or 'call')"

    matches, skipped = await _gather_option_matches(
        tradier, tickers, opt_type, target_delta, min_dte, max_dte
    )
    if not matches:
        return "(no options found matching criteria)"

    rows: list[dict[str, str]] = []
    for m in matches:
        base = m.strike if opt_type == "put" else m.stock_price
        ann_yield = (m.bid / base) * (365 / m.dte) * 100

        if opt_type == "put":
            otm_pct = (m.stock_price - m.strike) / m.stock_price * 100
        else:
            otm_pct = (m.strike - m.stock_price) / m.stock_price * 100

        c_over_y = otm_pct / ann_yield if ann_yield > 0 else 0
        spread = (m.ask - m.bid) / m.mid * 100 if m.mid > 0 else 0

        rows.append(
            {
                "Symbol": m.symbol,
                "Price": fmt_number(m.stock_price, 2),
                "Strike": fmt_number(m.strike, 0),
                "Exp": m.exp,
                "DTE": str(m.dte),
                "Delta": fmt_number(m.delta, 2),
                "Bid": fmt_number(m.bid, 2),
                "Ann Yld %": fmt_number(ann_yield, 1),
                "OTM %": fmt_number(otm_pct, 1),
                "C/Y": fmt_number(c_over_y, 2),
                "Spread %": fmt_number(spread, 1),
            }
        )

    rows.sort(key=lambda r: to_float(r["Ann Yld %"]) or 0, reverse=True)
    columns = [
        "Symbol",
        "Price",
        "Strike",
        "Exp",
        "DTE",
        "Delta",
        "Bid",
        "Ann Yld %",
        "OTM %",
        "C/Y",
        "Spread %",
    ]
    out = list_table(rows, columns)
    if skipped:
        out += f"\n\nSkipped (no chain/delta match): {', '.join(skipped)}"
    return out


@mcp.tool()
async def compare_debit_efficiency(
    ctx: Context,
    symbols: str,
    option_type: str = "call",
    target_delta: float = 0.30,
    min_dte: int = 30,
    max_dte: int = 45,
) -> str:
    """Compare debit strategy cost efficiency across multiple stocks to
    prioritize capital allocation when conviction is similar.

    Finds the option closest to target_delta for each symbol and computes:
    - Cost/Exposure: premium paid as % of delta-adjusted notional exposure.
      Uses ask price (conservative — what you'd actually pay). Lower = cheaper
      leverage (more directional bang per dollar).
    - Spread: bid/ask spread as % of mid price (informational — already reflected
      in the cost via ask pricing).

    symbols: comma-separated tickers (e.g. 'MU,ADBE,NVDA,LRCX').
    option_type: 'call' for long calls (default), 'put' for long puts.
    target_delta: absolute delta to target (default 0.30).
    min_dte: minimum days to expiration (default 30).
    max_dte: maximum days to expiration (default 45).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        return "(no symbols provided)"
    opt_type = option_type.lower()
    if opt_type not in ("put", "call"):
        return "(option_type must be 'put' or 'call')"

    matches, skipped = await _gather_option_matches(
        tradier, tickers, opt_type, target_delta, min_dte, max_dte
    )
    if not matches:
        return "(no options found matching criteria)"

    rows: list[dict[str, str]] = []
    for m in matches:
        abs_delta = abs(m.delta)
        cost_exp = (m.ask / (abs_delta * m.stock_price) * 100) if abs_delta > 0 else 0
        spread = (m.ask - m.bid) / m.mid * 100 if m.mid > 0 else 0

        rows.append(
            {
                "Symbol": m.symbol,
                "Price": fmt_number(m.stock_price, 2),
                "Strike": fmt_number(m.strike, 0),
                "Exp": m.exp,
                "DTE": str(m.dte),
                "Delta": fmt_number(m.delta, 2),
                "Ask": fmt_number(m.ask, 2),
                "Cost/Exp %": fmt_number(cost_exp, 1),
                "Spread %": fmt_number(spread, 1),
            }
        )

    rows.sort(key=lambda r: to_float(r["Cost/Exp %"]) or 0)
    columns = [
        "Symbol",
        "Price",
        "Strike",
        "Exp",
        "DTE",
        "Delta",
        "Ask",
        "Cost/Exp %",
        "Spread %",
    ]
    out = list_table(rows, columns)
    if skipped:
        out += f"\n\nSkipped (no chain/delta match): {', '.join(skipped)}"
    return out


# -- Pipeline tracking tools --

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
    return _entry_detail(entry)


# -- Catalyst tools --

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
