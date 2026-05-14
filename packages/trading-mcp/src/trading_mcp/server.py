from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.bea_client import BeaClient
from trading_clients.beige_book_client import BeigeBookClient
from trading_clients.bls_client import BlsClient
from trading_clients.cftc_client import CftcClient
from trading_clients.config import load_config
from trading_clients.edgar_client import EdgarClient
from trading_clients.eia_client import EiaClient
from trading_clients.factset_client import FactsetClient
from trading_clients.fed_client import FedClient
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fool_client import FoolClient
from trading_clients.fred_client import FredClient
from trading_clients.freightos_client import FreightosClient
from trading_clients.kalshi_client import KalshiClient
from trading_clients.morningstar_client import MorningstarClient
from trading_clients.naaim_client import NaaimClient
from trading_clients.playwright_host import PlaywrightHost
from trading_clients.polymarket_client import PolymarketClient
from trading_clients.portwatch_client import PortwatchClient
from trading_clients.reddit_client import RedditClient
from trading_clients.sentiment_client import SentimentClient
from trading_clients.squeeze_metrics_client import SqueezeMetricsClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.treasury_client import TreasuryClient
from trading_clients.twse_client import TwseClient
from trading_clients.webull_client import WebullClient

from trading_mcp.db import open_db
from trading_mcp.db.decisions import init_schema as init_decision_schema
from trading_mcp.db.pipeline import init_schema as init_pipeline_schema
from trading_mcp.db.rolls import init_schema as init_roll_schema
from trading_mcp.db.twse_revenue import init_schema as init_twse_revenue_schema
from trading_mcp.tools.account import mcp as account_mcp
from trading_mcp.tools.backtest import mcp as backtest_mcp
from trading_mcp.tools.beige_book import mcp as beige_book_mcp
from trading_mcp.tools.calendar import mcp as calendar_mcp
from trading_mcp.tools.cftc import mcp as cftc_mcp
from trading_mcp.tools.cn_market import mcp as cn_market_mcp
from trading_mcp.tools.crypto import mcp as crypto_mcp
from trading_mcp.tools.decisions import mcp as decisions_mcp
from trading_mcp.tools.earnings import mcp as earnings_mcp
from trading_mcp.tools.edgar import mcp as edgar_mcp
from trading_mcp.tools.eia import mcp as eia_mcp
from trading_mcp.tools.factset import mcp as factset_mcp
from trading_mcp.tools.freight import mcp as freight_mcp
from trading_mcp.tools.fundamentals import mcp as fundamentals_mcp
from trading_mcp.tools.ipo import mcp as ipo_mcp
from trading_mcp.tools.macro import mcp as macro_mcp
from trading_mcp.tools.naaim import mcp as naaim_mcp
from trading_mcp.tools.news import mcp as news_mcp
from trading_mcp.tools.options import mcp as options_mcp
from trading_mcp.tools.orders import mcp as orders_mcp
from trading_mcp.tools.pipeline import mcp as pipeline_mcp
from trading_mcp.tools.pipeline_catalysts import mcp as pipeline_catalysts_mcp
from trading_mcp.tools.prediction_markets import mcp as prediction_markets_mcp
from trading_mcp.tools.quotes import mcp as quotes_mcp
from trading_mcp.tools.rolls import mcp as rolls_mcp
from trading_mcp.tools.screens import mcp as screens_mcp
from trading_mcp.tools.signals import mcp as signals_mcp
from trading_mcp.tools.squeeze_metrics import mcp as squeeze_metrics_mcp
from trading_mcp.tools.treasury import mcp as treasury_mcp
from trading_mcp.tools.tsmc import mcp as tsmc_mcp


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
    if config.eia:
        ctx["eia"] = EiaClient(config.eia)
    if config.tastytrade:
        ctx["tastytrade"] = TastyTradeClient(config.tastytrade)
    ctx["reddit"] = RedditClient()
    ctx["fool"] = FoolClient()
    ctx["edgar"] = EdgarClient(config.edgar)
    ctx["bls"] = BlsClient()
    ctx["bea"] = BeaClient()
    ctx["fed"] = FedClient()
    ctx["cftc"] = CftcClient()
    ctx["polymarket"] = PolymarketClient()
    ctx["kalshi"] = KalshiClient()
    ctx["twse"] = TwseClient()
    ctx["treasury"] = TreasuryClient()
    ctx["freightos"] = FreightosClient()
    ctx["portwatch"] = PortwatchClient()
    ctx["beige_book"] = BeigeBookClient()
    ctx["squeeze_metrics"] = SqueezeMetricsClient()
    ctx["naaim"] = NaaimClient()
    ctx["factset"] = FactsetClient()
    # Shared Chromium for all Playwright-backed scrapers (SentimentClient,
    # MorningstarClient). One process, many isolated contexts. If Chromium
    # can't launch (missing binary, sandbox issue), all Playwright clients
    # are skipped and the server keeps running without them.
    playwright_host: PlaywrightHost | None = PlaywrightHost()
    try:
        await playwright_host.startup()
    except Exception:
        await playwright_host.close()
        playwright_host = None

    if playwright_host is not None:
        sentiment = SentimentClient(playwright_host)
        try:
            await sentiment.startup()
            ctx["sentiment"] = sentiment
        except Exception:
            await sentiment.close()
        # Morningstar transcript fallback used by get_earnings_transcript when
        # Motley Fool has no transcript for a ticker.
        morningstar = MorningstarClient(playwright_host)
        try:
            await morningstar.startup()
            ctx["morningstar"] = morningstar
        except Exception:
            await morningstar.close()
    db = open_db()
    init_pipeline_schema(db)
    init_roll_schema(db)
    init_decision_schema(db)
    init_twse_revenue_schema(db)
    ctx["db"] = db
    try:
        yield ctx
    finally:
        db.close()
        for v in ctx.values():
            if hasattr(v, "close") and callable(v.close) and v is not db:
                await v.close()
        # Shut Chromium down AFTER every client context has closed.
        if playwright_host is not None:
            await playwright_host.close()


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
mcp.mount(cftc_mcp)
mcp.mount(prediction_markets_mcp)
mcp.mount(tsmc_mcp)
mcp.mount(treasury_mcp)
mcp.mount(freight_mcp)
mcp.mount(beige_book_mcp)
mcp.mount(squeeze_metrics_mcp)
mcp.mount(naaim_mcp)
mcp.mount(eia_mcp)
mcp.mount(factset_mcp)
mcp.mount(backtest_mcp)
mcp.mount(earnings_mcp)
mcp.mount(edgar_mcp)
mcp.mount(ipo_mcp)
mcp.mount(signals_mcp)
mcp.mount(pipeline_mcp)
mcp.mount(pipeline_catalysts_mcp)
mcp.mount(rolls_mcp)
mcp.mount(decisions_mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
