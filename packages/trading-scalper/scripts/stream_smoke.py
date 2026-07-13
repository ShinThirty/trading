"""Live smoke test for the DXLink (dxFeed) streaming feed — the scalper's live feed.

Fetches a dxFeed streamer token via Tastytrade OAuth from ~/.tradingrc, streams a few
symbols for a bounded window, and prints the parsed neutral events — proving the token
fetch + DXLink channel handshake + COMPACT wire parsing end to end against the real feed.

    uv run --package trading-scalper python packages/trading-scalper/scripts/stream_smoke.py
    # ...append: --symbols /MESU26:XCME SPX --seconds 15 --max-events 15
"""

import argparse
import asyncio
import time

import httpx
from trading_clients.config import load_config
from trading_clients.dxlink_stream_client import DxLinkStreamClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_scalper.contract import ContractError, resolve_contract


async def _consume(
    client: DxLinkStreamClient,
    symbols: list[str],
    max_events: int,
    counts: dict[str, int],
) -> None:
    async for event in client.stream(symbols):
        counts[type(event).__name__] = counts.get(type(event).__name__, 0) + 1
        print(f"  {event}")
        if sum(counts.values()) >= max_events:
            return


async def run(symbols: list[str] | None, seconds: float, max_events: int) -> None:
    cfg = load_config()
    if cfg.tastytrade is None:
        raise SystemExit(
            "No [tastytrade] section in ~/.tradingrc (DXLink streams via Tastytrade OAuth)"
        )

    tasty = TastyTradeClient(cfg.tastytrade)
    if not symbols:  # default: the exchange's live /MES contract + its cash-index reference
        try:
            contract = await resolve_contract(tasty, "/MES")
        except ContractError as exc:
            await tasty.close()
            raise SystemExit(f"contract: {exc}") from exc
        symbols = [contract.symbol, contract.reference]

    print(f"symbols={symbols} window={seconds}s")
    print("connecting to Tastytrade DXLink (dxFeed)...")
    client = DxLinkStreamClient(tasty.get_quote_token)
    counts: dict[str, int] = {}
    start = time.monotonic()
    try:
        await asyncio.wait_for(
            _consume(client, symbols, max_events, counts),
            timeout=seconds,
        )
    except TimeoutError:
        pass
    except httpx.HTTPStatusError as exc:
        raise SystemExit(
            f"Tastytrade quote-token fetch failed: HTTP {exc.response.status_code}. "
            "401/403 means the OAuth token is invalid/expired or the account isn't a "
            "funded customer (DXLink futures streaming needs a real tastytrade customer)."
        ) from exc
    finally:
        await client.close()
        await tasty.close()

    elapsed = time.monotonic() - start
    total = sum(counts.values())
    print(f"\n{total} events in {elapsed:.1f}s — {counts or 'NONE'}")
    if total == 0:
        print(
            "No events. The cash index is quiet outside RTH; /MES trades ~23h — "
            "check the symbols + token if the futures session is open."
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="default: the exchange's active-month /MES contract + SPX",
    )
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--max-events", type=int, default=15)
    args = ap.parse_args()
    asyncio.run(run(args.symbols, args.seconds, args.max_events))


if __name__ == "__main__":
    main()
