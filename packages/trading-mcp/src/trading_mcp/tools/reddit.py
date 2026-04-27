import re

from fastmcp import Context, FastMCP
from trading_clients.endpoints import reddit as r

from trading_mcp.helpers import _reddit

mcp = FastMCP("reddit-tools")


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
    req = r.SearchRequest(query=query, subreddit=subreddit, sort=sort,
                          time_filter=time_filter, limit=limit)
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
    req = r.SubredditRequest(subreddit=subreddit, sort=sort,
                             time_filter=time_filter, limit=limit)
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
    req = r.PostRequest(post_id=post_id, comment_limit=comment_limit,
                        comment_sort=comment_sort)
    resp = await client.get(r.POST, req)
    return resp.to_output()
