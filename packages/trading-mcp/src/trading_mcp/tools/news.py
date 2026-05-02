"""News, sentiment, and discussion sources: company/market news, Alpha Vantage
sentiment scores, Reddit posts/comments, YouTube transcripts.
"""

import asyncio
import re

from fastmcp import Context, FastMCP
from trading_clients.endpoints import alphavantage as av
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import reddit as r

from trading_mcp.helpers import _alphavantage, _finnhub, _reddit

mcp = FastMCP("news-tools")


@mcp.tool()
async def get_company_news(
    ctx: Context, symbol: str, from_date: str, to_date: str, limit: int = 20
) -> str:
    """Get recent news articles for a specific company.

    symbol: ticker symbol (e.g. 'AAPL').
    from_date: start date (YYYY-MM-DD).
    to_date: end date (YYYY-MM-DD).
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (
        await _finnhub(ctx).get(fh.COMPANY_NEWS, fh.CompanyNewsRequest(symbol, from_date, to_date))
    ).to_output()


@mcp.tool()
async def get_market_news(ctx: Context, category: str = "general", limit: int = 20) -> str:
    """Get general market news headlines.

    category: 'general', 'forex', 'crypto', or 'merger'.
    limit: max number of articles to return (default 20).

    Requires [finnhub] section in ~/.tradingrc.
    """
    return (await _finnhub(ctx).get(fh.MARKET_NEWS, fh.MarketNewsRequest(category))).to_output()


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


def _post_id_from_url(url: str) -> str:
    m = re.search(r"/comments/([a-z0-9]+)", url)
    if m:
        return m.group(1)
    return url.strip()


@mcp.tool()
async def search_reddit(
    ctx: Context,
    query: str,
    subreddit: str = "all",
    sort: str = "relevance",
    time_filter: str = "week",
    limit: int = 10,
) -> str:
    """Search Reddit for posts matching a query.

    Useful for finding discussion about a specific ticker, sector, or market event.

    query: Search query (e.g. '$AAPL earnings', 'semiconductor cycle').
    subreddit: Subreddit to search within (default 'all'). Use 'options', 'thetagang',
      'wallstreetbets', 'stocks', 'investing', etc. for targeted searches.
    sort: Sort order — 'relevance', 'hot', 'top', 'new', 'comments'.
    time_filter: Time window — 'hour', 'day', 'week', 'month', 'year', 'all'.
    limit: Max posts to return (1-25, default 10).
    """
    client = _reddit(ctx)
    req = r.SearchRequest(
        query=query, subreddit=subreddit, sort=sort, time_filter=time_filter, limit=limit
    )
    resp = await client.get(r.SEARCH, req)
    if not resp.posts:
        return f"No results for '{query}' in r/{subreddit}"
    header = f"**Search: '{query}' in r/{subreddit}** (sort={sort}, time={time_filter})\n\n"
    return header + resp.to_output()


@mcp.tool()
async def get_subreddit_posts(
    ctx: Context,
    subreddit: str,
    sort: str = "hot",
    time_filter: str = "week",
    limit: int = 10,
) -> str:
    """Get posts from a subreddit.

    subreddit: Subreddit name (e.g. 'thetagang', 'options', 'stocks').
    sort: Sort order — 'hot', 'new', 'top', 'rising'.
    time_filter: Time window for 'top' sort — 'hour', 'day', 'week', 'month', 'year', 'all'.
    limit: Max posts to return (1-25, default 10).
    """
    client = _reddit(ctx)
    req = r.SubredditRequest(subreddit=subreddit, sort=sort, time_filter=time_filter, limit=limit)
    resp = await client.get(r.SUBREDDIT, req)
    if not resp.posts:
        return f"No posts found in r/{subreddit}"
    header = f"**r/{subreddit}** ({sort})\n\n"
    return header + resp.to_output(include_subreddit=False)


@mcp.tool()
async def get_reddit_post(
    ctx: Context,
    url: str,
    comment_limit: int = 15,
    comment_sort: str = "best",
) -> str:
    """Get a Reddit post and its top comments.

    url: Full Reddit post URL or post ID.
    comment_limit: Max top-level comments to return (1-30, default 15).
    comment_sort: Comment sort — 'best', 'top', 'new', 'controversial', 'old', 'qa'.
    """
    client = _reddit(ctx)
    post_id = _post_id_from_url(url)
    req = r.PostRequest(post_id=post_id, comment_limit=comment_limit, comment_sort=comment_sort)
    resp = await client.get(r.POST, req)
    return resp.to_output()


@mcp.tool()
async def get_youtube_transcript(ctx: Context, url: str) -> str:
    """Get the transcript of a YouTube video.

    Extracts auto-generated or manual captions and returns the full text.
    Useful for analyzing financial commentary, earnings calls, or market analysis videos.

    url: YouTube video URL or video ID (e.g. 'https://www.youtube.com/watch?v=abc123'
      or just 'abc123').
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = url
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        video_id = m.group(1)

    api = YouTubeTranscriptApi()
    transcript = await asyncio.to_thread(api.fetch, video_id)
    full_text = " ".join(s.text for s in transcript.snippets)
    kind = "auto-generated" if transcript.is_generated else "manual"
    return f"**Video ID:** {video_id}\n**Language:** {transcript.language} ({kind})\n\n{full_text}"
