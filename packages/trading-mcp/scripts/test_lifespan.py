"""Exercise the trading-mcp lifespan end-to-end via an in-memory FastMCP client.

Verifies that:
1. lifespan() startup completes (all 27 clients init, sqlite schemas open,
   Playwright host either starts or is skipped cleanly)
2. mounted subservers' tools are discoverable
3. a representative tool call succeeds (pipeline_list — sqlite-only, no
   external API config required)
4. lifespan() teardown completes (sqlite + every *.close() + Playwright host)

Run: uv run --package trading-mcp python packages/trading-mcp/scripts/test_lifespan.py
"""

from __future__ import annotations

import asyncio
import time

from fastmcp import Client
from trading_mcp.server import mcp


async def main() -> int:
    t0 = time.perf_counter()
    async with Client(mcp) as client:
        t_startup = time.perf_counter() - t0
        print(f"[startup]  lifespan ready in {t_startup:.2f}s")

        tools = await client.list_tools()
        print(f"[discover] {len(tools)} tools mounted")

        t1 = time.perf_counter()
        result = await client.call_tool("pipeline_list", {})
        t_call = time.perf_counter() - t1
        text = result.content[0].text if result.content else "<empty>"
        print(f"[call]     pipeline_list in {t_call:.2f}s")
        print(f"           → {text.splitlines()[0][:100]}")

        t2 = time.perf_counter()
    t_shutdown = time.perf_counter() - t2
    print(f"[shutdown] lifespan torn down in {t_shutdown:.2f}s")
    print(f"[total]    {time.perf_counter() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
