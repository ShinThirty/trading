#!/usr/bin/env python3
"""Prepopulate TSMC monthly revenue history into trading.db.

Two ways to seed:

  1. From the TWSE OpenAPI feed (default — no args):
     One call yields four months of coverage automatically: the current
     reporting month, the prior month, the same-month-prior-year anchor,
     and (when the current month is Feb or Mar) the derivable January
     revenue from YTD arithmetic. Run it any time to refresh.

  2. From a CSV of historical revenue (--csv path):
     Use this to backfill months that the OpenAPI feed can't cover.
     CSV columns (header required):
       year,month,revenue_thousands,yoy_pct
     Example row:
       2025,11,295823000,34.0
     revenue_thousands is NT$ thousands (matches the OpenAPI unit).
     yoy_pct is optional (leave the cell empty for unknown).

Both modes coexist — re-running the script is safe. Source priority gates
inside the DB layer prevent a manual_seed write from overwriting an
existing twse_openapi row.

Usage:
  uv run python packages/trading-mcp/scripts/seed_tsmc_revenue.py
  uv run python packages/trading-mcp/scripts/seed_tsmc_revenue.py --csv history.csv
  uv run python packages/trading-mcp/scripts/seed_tsmc_revenue.py --csv history.csv --no-openapi
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "trading-clients" / "src"))

from trading_clients.endpoints import twse  # noqa: E402
from trading_clients.twse_client import TwseClient  # noqa: E402
from trading_mcp.db import (
    open_db,  # noqa: E402
    twse_revenue,  # noqa: E402
)

TSMC_COMPANY_CODE = "2330"


async def seed_from_openapi(db) -> int:
    client = TwseClient()
    try:
        feed = await client.get(twse.LISTED_MONTHLY_REVENUE, twse.ListedMonthlyRevenueRequest())
    finally:
        await client.close()

    row = feed.by_code(TSMC_COMPANY_CODE)
    if row is None:
        print(f"TSMC ({TSMC_COMPANY_CODE}) not in feed ({len(feed.rows)} companies)")
        return 0

    yoy_part = f"  YoY={row.yoy_pct:+.1f}%" if row.yoy_pct is not None else ""
    print(
        f"OpenAPI headline: {row.year}-{row.month:02d}  "
        f"revenue={row.revenue_curr_thousands:,} NT$K{yoy_part}"
    )

    writes = 0

    async def _maybe(y: int, m: int, rev: int | None, yoy: float | None, source: str) -> None:
        nonlocal writes
        if rev is None:
            return
        wrote = await twse_revenue.upsert(
            db,
            company_code=TSMC_COMPANY_CODE,
            year=y,
            month=m,
            revenue_thousands=rev,
            yoy_pct=yoy,
            source=source,
        )
        if wrote:
            writes += 1
            yoy_str = f"{yoy:+.1f}%" if yoy is not None else "—"
            print(f"  + {y}-{m:02d}  rev={rev:>14,}  yoy={yoy_str:>7}  src={source}")

    await _maybe(row.year, row.month, row.revenue_curr_thousands, row.yoy_pct, "twse_openapi")

    prev_y = row.year if row.month > 1 else row.year - 1
    prev_m = row.month - 1 if row.month > 1 else 12
    await _maybe(prev_y, prev_m, row.revenue_prior_thousands, None, "twse_openapi")
    await _maybe(row.year - 1, row.month, row.revenue_lastyear_thousands, None, "twse_openapi")

    if row.ytd_revenue_thousands is not None and row.month == 2:
        jan = row.ytd_revenue_thousands - row.revenue_curr_thousands
        if jan > 0:
            await _maybe(row.year, 1, jan, None, "derived")
    elif (
        row.ytd_revenue_thousands is not None
        and row.month == 3
        and row.revenue_prior_thousands is not None
    ):
        jan = row.ytd_revenue_thousands - row.revenue_curr_thousands - row.revenue_prior_thousands
        if jan > 0:
            await _maybe(row.year, 1, jan, None, "derived")

    return writes


async def seed_from_csv(db, csv_path: Path) -> int:
    writes = 0
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        required = {"year", "month", "revenue_thousands"}
        if not required.issubset(reader.fieldnames or []):
            raise SystemExit(
                f"CSV must have header columns: {sorted(required)} (yoy_pct optional). "
                f"Got: {reader.fieldnames}"
            )
        for raw in reader:
            try:
                year = int(raw["year"])
                month = int(raw["month"])
                revenue = int(raw["revenue_thousands"].replace(",", ""))
            except (ValueError, KeyError) as exc:
                print(f"  ! skipping malformed row {raw}: {exc}")
                continue
            yoy_raw = (raw.get("yoy_pct") or "").strip()
            yoy: float | None
            try:
                yoy = float(yoy_raw) if yoy_raw else None
            except ValueError:
                yoy = None
            wrote = await twse_revenue.upsert(
                db,
                company_code=TSMC_COMPANY_CODE,
                year=year,
                month=month,
                revenue_thousands=revenue,
                yoy_pct=yoy,
                source="manual_seed",
            )
            if wrote:
                writes += 1
                yoy_str = f"{yoy:+.1f}%" if yoy is not None else "—"
                print(
                    f"  + {year}-{month:02d}  rev={revenue:>14,}  yoy={yoy_str:>7}  src=manual_seed"
                )
            else:
                print(f"  · {year}-{month:02d}  skipped (higher-priority row already cached)")
    return writes


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="CSV path for historical backfill")
    parser.add_argument(
        "--no-openapi",
        action="store_true",
        help="Skip the OpenAPI seed (use only --csv data)",
    )
    args = parser.parse_args()

    db = open_db()
    twse_revenue.init_schema(db)

    total = 0
    if not args.no_openapi:
        print("=== Seeding from TWSE OpenAPI ===")
        total += await seed_from_openapi(db)

    if args.csv is not None:
        if not args.csv.exists():
            raise SystemExit(f"CSV not found: {args.csv}")
        print(f"\n=== Seeding from CSV: {args.csv} ===")
        total += await seed_from_csv(db, args.csv)

    rows_after = await twse_revenue.count(db, TSMC_COMPANY_CODE)
    print(
        f"\n{total} new row(s) written. "
        f"DB now holds {rows_after} months for TSMC ({TSMC_COMPANY_CODE})."
    )
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
