"""Treasury Quarterly Refunding Announcement (QRA) texture tool.

Mirrors the get_fomc_decision_texture pattern: latest refunding statement +
prior refunding statement (for language diff) + rate context + intraday tape.
"""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients.endpoints import fred, treasury
from trading_clients.endpoints import tradier as t

from trading_mcp.helpers import _exc_summary, _fred, _tradier, _treasury

mcp = FastMCP("treasury-tools")


def _latest(obs: list[dict]) -> float | None:
    if not obs:
        return None
    try:
        return float(obs[0]["value"])
    except (ValueError, KeyError):
        return None


def _prior(obs: list[dict]) -> float | None:
    if len(obs) < 2:
        return None
    try:
        return float(obs[1]["value"])
    except (ValueError, KeyError):
        return None


def _warnings_section(warnings: list[str]) -> list[str]:
    if not warnings:
        return []
    lines = ["⚠ Data source warnings (some fetches failed):"]
    for w in warnings:
        lines.append(f"  • {w}")
    lines.append("")
    return lines


async def _qra_statements(
    treasury_client,
) -> tuple[
    "treasury.QraIndexResponse | None",
    "treasury.QraArchiveResponse | None",
    "treasury.QraStatementResponse | None",
    "treasury.QraStatementResponse | None",
    list[str],
]:
    """Discover latest + prior QRA Policy Statement URLs, then fetch both
    statements in parallel.

    Returns (idx, archive, latest_stmt, prior_stmt, warnings). Any failed
    step contributes a warning so the caller can surface it.
    """
    warnings: list[str] = []
    idx_archive_results = await asyncio.gather(
        treasury_client.get(treasury.QRA_LATEST_INDEX, treasury.EmptyRequest()),
        treasury_client.get(treasury.QRA_ARCHIVE, treasury.EmptyRequest()),
        return_exceptions=True,
    )
    idx_resp: treasury.QraIndexResponse | None = None
    if isinstance(idx_archive_results[0], BaseException):
        warnings.append(_exc_summary("Treasury QRA most-recent index", idx_archive_results[0]))
    else:
        idx_resp = idx_archive_results[0]
    archive_resp: treasury.QraArchiveResponse | None = None
    if isinstance(idx_archive_results[1], BaseException):
        warnings.append(_exc_summary("Treasury QRA archive", idx_archive_results[1]))
    else:
        archive_resp = idx_archive_results[1]

    latest_path = idx_resp.latest() if idx_resp else None
    prior_entry = archive_resp.prior_to(latest_path) if archive_resp else None
    prior_path = prior_entry.path if prior_entry else None

    if not latest_path:
        warnings.append("Treasury QRA: no latest Policy Statement link found")
        return idx_resp, archive_resp, None, None, warnings

    fetches = [
        treasury_client.get(treasury.QRA_STATEMENT, treasury.StatementPathRequest(latest_path))
    ]
    if prior_path:
        fetches.append(
            treasury_client.get(treasury.QRA_STATEMENT, treasury.StatementPathRequest(prior_path))
        )
    results = await asyncio.gather(*fetches, return_exceptions=True)

    latest_stmt: treasury.QraStatementResponse | None = None
    if isinstance(results[0], BaseException):
        warnings.append(_exc_summary(f"Treasury QRA latest {latest_path}", results[0]))
    else:
        latest_stmt = results[0]
    prior_stmt: treasury.QraStatementResponse | None = None
    if len(results) > 1:
        if isinstance(results[1], BaseException):
            warnings.append(_exc_summary(f"Treasury QRA prior {prior_path}", results[1]))
        else:
            prior_stmt = results[1]
    return idx_resp, archive_resp, latest_stmt, prior_stmt, warnings


@mcp.tool()
async def get_qra_texture(ctx: Context) -> str:
    """Latest Treasury Quarterly Refunding Announcement (QRA): refunding
    statement language + prior QRA for comparison + rate context.

    The QRA is released 4x/year (early Feb / May / Aug / Nov) on the
    Wednesday following Monday's borrowing estimate. The Wednesday Policy
    Statement details upcoming auction sizes (2y/3y/5y/7y/10y/20y/30y/FRN),
    bill-vs-coupon mix, buyback program updates, and forward guidance
    ("anticipates maintaining auction sizes for at least the next several
    quarters" → status quo; "anticipates increasing" → duration absorption
    ahead).

    Aggregates the Policy Statement (latest + prior so language deltas are
    inspectable in a single tool call) with FRED rate series for yield curve
    context (DTB3 / DGS2 / DGS5 / DGS10 / DGS30 / T10Y2Y) and Tradier
    intraday quotes for the rate-sensitive tape (TLT / IEF / IEI / SHY /
    TIP / SPY / UUP / VIX).

    Returns warnings + headline + yield curve + tape + latest statement +
    prior statement. Does not interpret — surfaces the data so judgment
    (especially the bill-vs-coupon mix shift and forward guidance language
    diff that drive QRA-day market reaction) happens in conversation.

    QRA-day is one of the most reliable single-event drivers for the long
    end of the curve. Aug 2023's coupon-increase announcement is widely
    credited with triggering that quarter's selloff in 30y; Yellen's 2024
    bill-skew is credited with the equity rally via reduced duration on
    dealer balance sheets.

    Requires [fred] + [tradier] sections in ~/.tradingrc.
    """
    fred_client = _fred(ctx)
    tradier = _tradier(ctx)
    treasury_client = _treasury(ctx)

    rate_specs = [
        ("DTB3", 2),
        ("DGS2", 2),
        ("DGS5", 2),
        ("DGS10", 2),
        ("DGS30", 2),
        ("T10Y2Y", 2),
    ]
    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest(sid, lim))
        for sid, lim in rate_specs
    ]
    # List the awaitables before gather so the result type stays homogeneous —
    # keeps the type checker from latching the QRA tuple shape onto results[0]
    # and reporting false positives downstream.
    tasks: list = [
        _qra_statements(treasury_client),
        tradier.get(t.QUOTES, t.GetQuotesRequest("TLT,IEF,IEI,SHY,TIP,SPY,UUP,VIX")),
        *fred_tasks,
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    warnings: list[str] = []
    qra_bundle = results[0]
    idx_resp: treasury.QraIndexResponse | None = None
    latest_stmt: treasury.QraStatementResponse | None = None
    prior_stmt: treasury.QraStatementResponse | None = None
    if isinstance(qra_bundle, BaseException):
        warnings.append(_exc_summary("Treasury QRA fetch (unexpected)", qra_bundle))
    else:
        idx_resp, _archive_resp, latest_stmt, prior_stmt, qra_warnings = qra_bundle
        warnings.extend(qra_warnings)

    tape_raw = results[1]
    tape_resp: t.QuotesResponse | None
    if isinstance(tape_raw, t.QuotesResponse):
        tape_resp = tape_raw
    else:
        tape_resp = None
        if isinstance(tape_raw, BaseException):
            warnings.append(_exc_summary("Tradier intraday quotes", tape_raw))

    obs_by_id: dict[str, list[dict]] = {}
    for i, (sid, _) in enumerate(rate_specs):
        r = results[2 + i]
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(f"FRED {sid}", r))
        else:
            obs_by_id[sid] = r.observations or []

    out: list[str] = []
    out.extend(_warnings_section(warnings))

    # Headline
    out.append("=== Headline ===")
    if latest_stmt and latest_stmt.release_date:
        out.append(f"Latest QRA Policy Statement: {latest_stmt.release_date}")
    elif idx_resp and idx_resp.latest():
        out.append(f"Latest QRA Policy Statement: {idx_resp.latest()}")
    if prior_stmt and prior_stmt.release_date:
        out.append(f"Prior QRA Policy Statement:  {prior_stmt.release_date}")

    # Yield curve
    out.append("")
    out.append("=== Yield curve (latest, prior in parens) ===")
    yield_labels = [
        ("DTB3", "3-month bill"),
        ("DGS2", "2-year note"),
        ("DGS5", "5-year note"),
        ("DGS10", "10-year note"),
        ("DGS30", "30-year bond"),
        ("T10Y2Y", "10y - 2y spread"),
    ]
    for sid, label in yield_labels:
        cur = _latest(obs_by_id.get(sid, []))
        prv = _prior(obs_by_id.get(sid, []))
        if cur is None:
            continue
        if sid == "T10Y2Y":
            prior_str = f" ({prv:+.2f}% prior)" if prv is not None else ""
            out.append(f"  {label:24s} {cur:+.2f}%{prior_str}")
        else:
            prior_str = f" ({prv:.2f}% prior)" if prv is not None else ""
            out.append(f"  {label:24s} {cur:.2f}%{prior_str}")

    # Tape
    out.append("")
    out.append("=== Tape (intraday) ===")
    if tape_resp and tape_resp.quotes:
        for q in tape_resp.quotes:
            sym = q.get("symbol", "")
            last = q.get("last")
            chg_pct = q.get("change_percentage")
            chg = q.get("change")
            if last is None:
                continue
            if sym == "VIX":
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg:+.2f})")
            else:
                out.append(f"  {sym:6s} {last:>7.2f}  ({chg_pct:+.2f}%)")
    else:
        out.append("  (tape unavailable)")

    # Latest statement
    out.append("")
    if latest_stmt and latest_stmt.text:
        date_str = latest_stmt.release_date or "?"
        out.append(f"=== QRA Policy Statement ({date_str}) ===")
        out.append(latest_stmt.text)
    else:
        out.append("=== QRA Policy Statement ===")
        out.append("(latest statement unavailable)")

    # Prior statement (for language diff)
    out.append("")
    if prior_stmt and prior_stmt.text:
        date_str = prior_stmt.release_date or "?"
        out.append(f"=== Prior QRA Policy Statement ({date_str}, for comparison) ===")
        out.append(prior_stmt.text)

    return "\n".join(out)


__all__ = ["mcp", "get_qra_texture"]
