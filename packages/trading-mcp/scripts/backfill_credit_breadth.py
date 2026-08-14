#!/usr/bin/env python3
"""Backfill FINRA corporate bond market breadth into the local SQLite history.

FINRA partitions `corporateMarketBreadth` on the trade date, so a history pull
is one HTTP round trip per session per universe. That's too slow to do inside a
tool call but perfectly fine as a batch: ~730 sessions x 2 universes lands in
roughly six minutes at the client's rate limit.

The point of storing it is that the *shadow period* only means something if
something accumulates. A signal read as a live snapshot each time leaves no
evidence behind, so no amount of elapsed time would ever qualify it for
promotion. This gives the 144A divergence a measurable base rate on day one
instead of six months from now.

Coverage note: the dataset's first session is **2023-07-28**. The window covers
the Oct-2023 duration selloff, the Aug-2024 vol shock, and the ~200bp HY OAS
widening into April 2025 — so it supports both a false-positive rate and (on a
single episode) a first look at whether the 144A divergence leads. See
analyze_credit_divergence.py.

Resumable and idempotent: sessions already stored, and dates FINRA confirmed
empty, are skipped without a request. Re-running after a partial run costs only
the remaining dates.

Usage:
  uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_credit_breadth.py
  uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_credit_breadth.py \
      --start 2025-01-01 --end 2026-08-14
  uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_credit_breadth.py \
      --status
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from trading_clients.config import load_config
from trading_clients.endpoint import Endpoint
from trading_clients.endpoints import finra
from trading_clients.finra_client import FinraClient
from trading_mcp.db import open_db
from trading_mcp.db.credit_breadth import (
    EMPTY_IS_FINAL_AFTER_DAYS,
    UNIVERSE_144A,
    UNIVERSE_ALL,
    coverage,
    init_schema,
    known_dates,
    mark_empty,
    upsert_session,
)

# The dataset's first session sits in H2 2023; probing earlier just burns
# requests on 204s. Overridable with --start.
DEFAULT_START = date(2023, 7, 1)

UNIVERSES = (
    (UNIVERSE_ALL, finra.MARKET_BREADTH),
    (UNIVERSE_144A, finra.MARKET_BREADTH_144A),
)

# Requests in flight per batch. The client's own limiter (4/s) is the real
# throttle; this just bounds how much sits queued behind it.
BATCH = 24


@dataclass
class Stats:
    written: int = 0
    empty: int = 0
    pending: int = 0
    skipped: int = 0
    failed: int = 0


def weekdays(start: date, end: date) -> list[date]:
    """Every Mon-Fri from start to end inclusive, oldest first.

    Weekends are dropped up front — FINRA answers them with an empty 204, and
    at one request per date that is pure waste.
    """
    out: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


async def fetch_one(
    client: FinraClient, endpoint: Endpoint, day: date
) -> finra.MarketBreadthResponse | Exception:
    """One session. Failures are returned, not raised — a single bad date
    shouldn't abandon a multi-thousand-request run, and the date stays unstored
    so the next run retries it."""
    try:
        return await client.post(endpoint, finra.TradeDateRequest(trade_date=day, limit=50))
    except Exception as exc:
        return exc


async def backfill(start: date, end: date, verbose: bool) -> Stats:
    config = load_config()
    if config.finra is None:
        print(
            "FINRA not configured. Add [finra] api_client_id/api_secret to ~/.tradingrc.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    conn = open_db()  # sets a busy_timeout — the MCP server may hold the same DB
    init_schema(conn)
    client = FinraClient(config.finra)
    stats = Stats()

    try:
        for universe, endpoint in UNIVERSES:
            done = await known_dates(conn, universe)
            todo = [d for d in weekdays(start, end) if d.isoformat() not in done]
            stats.skipped += len(weekdays(start, end)) - len(todo)
            print(f"[{universe}] {len(todo)} session(s) to fetch, {len(done)} already stored")

            for i in range(0, len(todo), BATCH):
                chunk = todo[i : i + BATCH]
                results = await asyncio.gather(*[fetch_one(client, endpoint, d) for d in chunk])
                for day, result in zip(chunk, results, strict=True):
                    if isinstance(result, Exception):
                        stats.failed += 1
                        print(f"  {day} [{universe}] FAILED: {type(result).__name__}: {result}")
                        continue
                    if not result.rows:
                        if (date.today() - day).days >= EMPTY_IS_FINAL_AFTER_DAYS:
                            await mark_empty(conn, day, universe)
                            stats.empty += 1
                        else:
                            # Too recent to call — likely just unpublished.
                            stats.pending += 1
                        continue
                    await upsert_session(
                        conn,
                        day,
                        universe,
                        [
                            {
                                "grade": r.grade,
                                "total_trades": r.total_trades,
                                "advances": r.advances,
                                "declines": r.declines,
                                "unchanged": r.unchanged,
                                "fifty_two_week_high": r.fifty_two_week_high,
                                "fifty_two_week_low": r.fifty_two_week_low,
                                "total_volume_mm": r.total_volume_mm,
                            }
                            for r in result.rows
                        ],
                    )
                    stats.written += 1
                    if verbose:
                        print(f"  {day} [{universe}] {len(result.rows)} grade rows")
                done_n = min(i + BATCH, len(todo))
                print(f"  [{universe}] {done_n}/{len(todo)}", end="\r", flush=True)
            print()
    finally:
        await client.close()
        conn.close()

    return stats


async def show_status() -> None:
    conn = open_db()
    init_schema(conn)
    try:
        cov = await coverage(conn)
    finally:
        conn.close()
    if not cov["sessions"]:
        print("credit_breadth: empty — run the backfill.")
        return
    print(f"credit_breadth: {cov['sessions']} sessions, {cov['first_date']} → {cov['last_date']}")
    for universe, n in sorted(cov["by_universe"].items()):
        print(f"  {universe:>5}: {n} sessions")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=str, default=DEFAULT_START.isoformat())
    ap.add_argument("--end", type=str, default=date.today().isoformat())
    ap.add_argument("--status", action="store_true", help="show stored coverage and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.status:
        asyncio.run(show_status())
        return

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    stats = asyncio.run(backfill(start, end, args.verbose))
    print(
        f"\nwritten={stats.written}  empty(holiday/pre-history)={stats.empty}  "
        f"pending(not published yet)={stats.pending}  "
        f"already-stored={stats.skipped}  failed={stats.failed}"
    )
    asyncio.run(show_status())


if __name__ == "__main__":
    main()
