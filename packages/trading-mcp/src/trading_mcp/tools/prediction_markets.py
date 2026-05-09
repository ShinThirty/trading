"""Prediction-market tools (Polymarket + Kalshi).

Generic by-key fetcher: surfaces market-implied probabilities on a curated
event so directional bets can be benchmarked against what's already priced.

Both sources expose the same shape (event with child binary markets); we
normalize them to a common output table so the LLM doesn't have to know the
upstream schema.
"""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients.endpoints import kalshi as kl
from trading_clients.endpoints import polymarket as pm

from trading_mcp.helpers import _exc_summary, _kalshi, _polymarket

mcp = FastMCP("prediction-markets-tools")


@mcp.tool()
async def get_prediction_market(ctx: Context, source: str, key: str) -> str:
    """Fetch implied probabilities for one prediction-market event.

    source: "polymarket" or "kalshi"
    key:
      - Polymarket: event slug from the URL (e.g. `fed-decision-in-june-825`
        for https://polymarket.com/event/fed-decision-in-june-825).
      - Kalshi: event ticker (e.g. `KXFED-26JUN`, `KXFEDDECISION-26JUN`).

    Returns a table of all child outcomes with implied probability, bid/ask
    (Kalshi only — Polymarket doesn't quote book on the gamma API), and 24h
    volume. Outcomes are sorted by descending implied probability.

    Use these probabilities as a "what's priced in" benchmark when sizing
    directional bets — if you think the market underprices a tail outcome,
    the contract gives you a clean number to disagree with.
    """
    src = source.strip().lower()
    if src == "polymarket":
        client = _polymarket(ctx)
        try:
            resp = await client.get(pm.GET_EVENT_BY_SLUG, pm.GetEventBySlugRequest(key))
        except Exception as exc:
            return f"Polymarket fetch failed for slug `{key}`: {_exc_summary('polymarket', exc)}"
        if not resp.event.outcomes:
            return (
                f"No outcomes returned from Polymarket for slug `{key}` — "
                "slug may be wrong, closed, or non-binary structure."
            )
        return resp.to_output()
    if src == "kalshi":
        client = _kalshi(ctx)
        try:
            resp = await client.get(kl.GET_EVENT_BY_TICKER, kl.GetEventByTickerRequest(key))
        except Exception as exc:
            return f"Kalshi fetch failed for ticker `{key}`: {_exc_summary('kalshi', exc)}"
        if not resp.event.outcomes:
            return (
                f"No outcomes returned from Kalshi for ticker `{key}` — "
                "ticker may be wrong, settled, or empty."
            )
        return resp.to_output()
    return f"Unknown source '{source}'. Valid: polymarket, kalshi."


@mcp.tool()
async def compare_prediction_markets(ctx: Context, polymarket_slug: str, kalshi_ticker: str) -> str:
    """Pull the same event from both Polymarket and Kalshi side-by-side.

    Useful for cross-checking: if both venues agree on implied probability the
    signal is robust, divergences usually trace to liquidity/fee distortions
    or one venue having stale book.

    polymarket_slug: Polymarket event slug
    kalshi_ticker: Kalshi event ticker

    Both fetches run concurrently. Errors on one side don't block the other.
    """
    p_client = _polymarket(ctx)
    k_client = _kalshi(ctx)

    p_task = p_client.get(pm.GET_EVENT_BY_SLUG, pm.GetEventBySlugRequest(polymarket_slug))
    k_task = k_client.get(kl.GET_EVENT_BY_TICKER, kl.GetEventByTickerRequest(kalshi_ticker))
    p_resp, k_resp = await asyncio.gather(p_task, k_task, return_exceptions=True)

    out: list[str] = []
    if isinstance(p_resp, BaseException):
        out.append(f"### Polymarket\n_fetch failed: {_exc_summary('polymarket', p_resp)}_")
    else:
        out.append(p_resp.to_output())
    out.append("")
    if isinstance(k_resp, BaseException):
        out.append(f"### Kalshi\n_fetch failed: {_exc_summary('kalshi', k_resp)}_")
    else:
        out.append(k_resp.to_output())
    return "\n".join(out)
