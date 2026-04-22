from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.config import load_config
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fred_client import FredClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.webull_client import WebullClient

from trading_mcp.db import open_db
from trading_mcp.pipeline_store import init_schema
from trading_mcp.tools.alphavantage import mcp as alphavantage_mcp
from trading_mcp.tools.btc import mcp as btc_mcp
from trading_mcp.tools.finnhub import mcp as finnhub_mcp
from trading_mcp.tools.fmp import mcp as fmp_mcp
from trading_mcp.tools.fred import mcp as fred_mcp
from trading_mcp.tools.market_regime import mcp as regime_mcp
from trading_mcp.tools.pipeline import mcp as pipeline_mcp
from trading_mcp.tools.signals import mcp as signals_mcp
from trading_mcp.tools.tastytrade import mcp as tastytrade_mcp
from trading_mcp.tools.tradier import mcp as tradier_mcp
from trading_mcp.tools.webull import mcp as webull_mcp
from trading_mcp.tools.yahoo import mcp as yahoo_mcp
from trading_mcp.tools.youtube import mcp as youtube_mcp


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    config = load_config()
    ctx: dict[str, Any] = {"webull": WebullClient(config.webull)}
    if config.tradier:
        ctx["tradier"] = TradierClient(config.tradier)
    if config.finnhub:
        ctx["finnhub"] = FinnhubClient(config.finnhub)
    if config.fmp:
        ctx["fmp"] = FmpClient(config.fmp)
    if config.fred:
        ctx["fred"] = FredClient(config.fred)
    if config.alphavantage:
        ctx["alphavantage"] = AlphaVantageClient(config.alphavantage)
    if config.tastytrade:
        ctx["tastytrade"] = TastyTradeClient(config.tastytrade)
    db = open_db()
    init_schema(db)
    ctx["db"] = db
    try:
        yield ctx
    finally:
        db.close()
        for v in ctx.values():
            if hasattr(v, "aclose"):
                await v.aclose()


mcp = FastMCP("trading-mcp", lifespan=lifespan)

mcp.mount(webull_mcp)
mcp.mount(tradier_mcp)
mcp.mount(finnhub_mcp)
mcp.mount(fmp_mcp)
mcp.mount(fred_mcp)
mcp.mount(regime_mcp)
mcp.mount(btc_mcp)
mcp.mount(signals_mcp)
mcp.mount(pipeline_mcp)
mcp.mount(alphavantage_mcp)
mcp.mount(tastytrade_mcp)
mcp.mount(yahoo_mcp)
mcp.mount(youtube_mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
