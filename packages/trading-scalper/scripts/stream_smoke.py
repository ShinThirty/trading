"""Live smoke test for the Tradier streaming feed.

Connects with the production Tradier token from ~/.tradingrc, streams a few
symbols for a bounded window, and prints the parsed neutral events — proving the
session handshake + WebSocket + wire parsing end to end against the real feed.

    uv run --package trading-scalper python packages/trading-scalper/scripts/stream_smoke.py
    # ...append: --symbols SPY QQQ --seconds 15 --max-events 15
"""

import argparse
import asyncio
import time

import httpx
from trading_clients.config import load_config
from trading_clients.tradier_stream_client import TradierStreamClient


async def _consume(
    client: TradierStreamClient,
    symbols: list[str],
    filters: list[str],
    max_events: int,
    counts: dict[str, int],
) -> None:
    async for event in client.stream(symbols, tuple(filters)):
        counts[type(event).__name__] = counts.get(type(event).__name__, 0) + 1
        print(f"  {event}")
        if sum(counts.values()) >= max_events:
            return


async def run(symbols: list[str], filters: list[str], seconds: float, max_events: int) -> None:
    cfg = load_config()
    if cfg.tradier is None:
        raise SystemExit("No [tradier] section in ~/.tradingrc")

    print(f"symbols={symbols} filters={filters} window={seconds}s sandbox={cfg.tradier.sandbox}")
    print("connecting to Tradier streaming (production host)...")
    client = TradierStreamClient(cfg.tradier.api_token)
    counts: dict[str, int] = {}
    start = time.monotonic()
    try:
        await asyncio.wait_for(
            _consume(client, symbols, filters, max_events, counts),
            timeout=seconds,
        )
    except TimeoutError:
        pass
    except httpx.HTTPStatusError as exc:
        raise SystemExit(
            f"Tradier session-create failed: HTTP {exc.response.status_code}. "
            "401/403 means the token isn't authorized for production streaming."
        ) from exc
    finally:
        await client.close()

    elapsed = time.monotonic() - start
    total = sum(counts.values())
    print(f"\n{total} events in {elapsed:.1f}s — {counts or 'NONE'}")
    if total == 0:
        print("No events. If the market is open, check the token is production and symbols valid.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"])
    ap.add_argument("--filters", nargs="+", default=["quote", "trade", "timesale"])
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--max-events", type=int, default=15)
    args = ap.parse_args()
    asyncio.run(run(args.symbols, args.filters, args.seconds, args.max_events))


if __name__ == "__main__":
    main()
