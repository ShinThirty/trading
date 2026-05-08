from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.bls_client import BlsClient
from trading_clients.config import load_config
from trading_clients.edgar_client import EdgarClient
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fool_client import FoolClient
from trading_clients.fred_client import FredClient
from trading_clients.reddit_client import RedditClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.webull_client import WebullClient

from trading_mcp.db import open_db
from trading_mcp.db.decisions import init_schema as init_decision_schema
from trading_mcp.db.pipeline import init_schema as init_pipeline_schema
from trading_mcp.db.rolls import init_schema as init_roll_schema
from trading_mcp.tools.account import mcp as account_mcp
from trading_mcp.tools.backtest import mcp as backtest_mcp
from trading_mcp.tools.calendar import mcp as calendar_mcp
from trading_mcp.tools.cn_market import mcp as cn_market_mcp
from trading_mcp.tools.crypto import mcp as crypto_mcp
from trading_mcp.tools.decisions import mcp as decisions_mcp
from trading_mcp.tools.earnings import mcp as earnings_mcp
from trading_mcp.tools.fundamentals import mcp as fundamentals_mcp
from trading_mcp.tools.macro import mcp as macro_mcp
from trading_mcp.tools.news import mcp as news_mcp
from trading_mcp.tools.options import mcp as options_mcp
from trading_mcp.tools.orders import mcp as orders_mcp
from trading_mcp.tools.pipeline import mcp as pipeline_mcp
from trading_mcp.tools.pipeline_catalysts import mcp as pipeline_catalysts_mcp
from trading_mcp.tools.quotes import mcp as quotes_mcp
from trading_mcp.tools.rolls import mcp as rolls_mcp
from trading_mcp.tools.screens import mcp as screens_mcp
from trading_mcp.tools.signals import mcp as signals_mcp


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
    ctx["reddit"] = RedditClient()
    ctx["fool"] = FoolClient()
    ctx["edgar"] = EdgarClient(config.edgar)
    ctx["bls"] = BlsClient()
    db = open_db()
    init_pipeline_schema(db)
    init_roll_schema(db)
    init_decision_schema(db)
    ctx["db"] = db
    try:
        yield ctx
    finally:
        db.close()
        for v in ctx.values():
            if hasattr(v, "close") and callable(v.close) and v is not db:
                await v.close()


mcp = FastMCP("trading-mcp", lifespan=lifespan)

mcp.mount(account_mcp)
mcp.mount(orders_mcp)
mcp.mount(quotes_mcp)
mcp.mount(options_mcp)
mcp.mount(fundamentals_mcp)
mcp.mount(calendar_mcp)
mcp.mount(macro_mcp)
mcp.mount(news_mcp)
mcp.mount(screens_mcp)
mcp.mount(crypto_mcp)
mcp.mount(cn_market_mcp)
mcp.mount(backtest_mcp)
mcp.mount(earnings_mcp)
mcp.mount(signals_mcp)
mcp.mount(pipeline_mcp)
mcp.mount(pipeline_catalysts_mcp)
mcp.mount(rolls_mcp)
mcp.mount(decisions_mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
