from fastmcp import Context, FastMCP
from trading_clients.endpoints import alphavantage as av

from trading_mcp.helpers import _alphavantage

mcp = FastMCP("alphavantage-tools")


@mcp.tool()
async def get_news_sentiment(
    ctx: Context,
    tickers: str | None = None,
    topics: str | None = None,
    limit: int = 10,
) -> str:
    """Get news articles with AI-generated sentiment scores per ticker.

    tickers: comma-separated symbols to filter by (e.g. 'AAPL,TSLA'). Omit for broad news.
    topics: comma-separated topic filters — 'earnings', 'ipo', 'mergers_and_acquisitions',
      'financial_markets', 'technology', etc. Omit for all topics.
    limit: max articles to return (default 10, max 50).

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return (
        await _alphavantage(ctx).get(
            av.SENTIMENT, av.SentimentRequest(tickers, topics, limit=limit)
        )
    ).to_output()


@mcp.tool()
async def get_top_movers(ctx: Context) -> str:
    """Get today's top market movers: top 20 gainers, top 20 losers, and most actively
    traded stocks.

    Rate limit: 25 requests/day. Use sparingly.
    Requires [alphavantage] section in ~/.tradingrc.
    """
    return (await _alphavantage(ctx).get(av.MOVERS, av.MoversRequest())).to_output()
