import asyncio
import sqlite3
import tempfile
from datetime import date
from typing import Any

from fastmcp import Context
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.bea_client import BeaClient
from trading_clients.bls_client import BlsClient
from trading_clients.edgar_client import EdgarClient
from trading_clients.endpoints import tradier as t
from trading_clients.fed_client import FedClient
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fool_client import FoolClient
from trading_clients.fred_client import FredClient
from trading_clients.reddit_client import RedditClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.webull_client import WebullClient


def _year_ago(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _db(ctx: Context) -> sqlite3.Connection:
    return ctx.lifespan_context["db"]


def _webull(ctx: Context) -> WebullClient:
    return ctx.lifespan_context["webull"]


def _tradier(ctx: Context) -> TradierClient:
    client = ctx.lifespan_context.get("tradier")
    if client is None:
        raise RuntimeError("Tradier not configured. Add [tradier] section to ~/.tradingrc")
    return client


def _finnhub(ctx: Context) -> FinnhubClient:
    client = ctx.lifespan_context.get("finnhub")
    if client is None:
        raise RuntimeError("Finnhub not configured. Add [finnhub] section to ~/.tradingrc")
    return client


def _fmp(ctx: Context) -> FmpClient:
    client = ctx.lifespan_context.get("fmp")
    if client is None:
        raise RuntimeError("FMP not configured. Add [fmp] section to ~/.tradingrc")
    return client


def _fred(ctx: Context) -> FredClient:
    client = ctx.lifespan_context.get("fred")
    if client is None:
        raise RuntimeError("FRED not configured. Add [fred] section to ~/.tradingrc")
    return client


def _alphavantage(ctx: Context) -> AlphaVantageClient:
    client = ctx.lifespan_context.get("alphavantage")
    if client is None:
        raise RuntimeError(
            "Alpha Vantage not configured. Add [alphavantage] section to ~/.tradingrc"
        )
    return client


def _tastytrade(ctx: Context) -> TastyTradeClient:
    client = ctx.lifespan_context.get("tastytrade")
    if client is None:
        raise RuntimeError(
            "TastyTrade not configured. Add [tastytrade] section to ~/.tradingrc "
            "with client_secret and refresh_token."
        )
    return client


def _reddit(ctx: Context) -> RedditClient:
    return ctx.lifespan_context["reddit"]


def _fool(ctx: Context) -> FoolClient:
    return ctx.lifespan_context["fool"]


def _edgar(ctx: Context) -> EdgarClient:
    return ctx.lifespan_context["edgar"]


def _bls(ctx: Context) -> BlsClient:
    return ctx.lifespan_context["bls"]


def _bea(ctx: Context) -> BeaClient:
    return ctx.lifespan_context["bea"]


def _fed(ctx: Context) -> FedClient:
    return ctx.lifespan_context["fed"]


async def _check_market(ctx: Context, order_type: str, extended_hours: bool) -> None:
    tradier = ctx.lifespan_context.get("tradier")
    if tradier is None:
        return
    clock = await tradier.get(t.CLOCK, t.EmptyRequest())
    state = clock.data.get("state", "closed")
    if order_type == "MARKET" and state != "open" and not extended_hours:
        raise RuntimeError(
            f"MARKET orders require regular hours (state: {state}). "
            "Use a LIMIT order, or wait for market open."
        )


async def _cached(cache: Any, key: str, ttl: int, fn: Any, *args: Any, **kwargs: Any) -> Any:
    hit = cache.get(key, ttl)
    if hit is not None:
        return hit
    result = await asyncio.to_thread(fn, *args, **kwargs)
    cache.put(key, result)
    return result


async def _retry(fn: Any, *args: Any, retries: int = 2, delay: float = 2, **kwargs: Any) -> Any:
    for attempt in range(retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception:
            if attempt < retries:
                await asyncio.sleep(delay)
                continue
            raise


def _exc_summary(source: str, exc: BaseException) -> str:
    """One-line description of a failed scrape/API call, suitable for surfacing
    in tool output as a warning or error message. Truncates long messages and
    drops multi-line tracebacks."""
    raw = str(exc).strip()
    msg = raw.splitlines()[0] if raw else ""
    return f"{source}: {type(exc).__name__}{f': {msg[:120]}' if msg else ''}"


async def _write_temp_file(content: str, suffix: str, prefix: str) -> str:

    def _sync_write() -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, prefix=prefix, delete=False)
        f.write(content)
        f.close()
        return f.name

    return await asyncio.to_thread(_sync_write)
