from fastmcp import Context, FastMCP

from trading_mcp.helpers import _reddit

mcp = FastMCP("reddit-tools")


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


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
    reddit = _reddit(ctx)
    limit = min(max(limit, 1), 25)
    sub = await reddit.subreddit(subreddit)
    results: list[str] = []
    async for post in sub.search(query, sort=sort, time_filter=time_filter, limit=limit):
        score = post.score
        comments = post.num_comments
        selftext = _truncate(post.selftext) if post.selftext else ""
        entry = (
            f"### {post.title}\n"
            f"r/{post.subreddit} · {score} pts · {comments} comments · u/{post.author}\n"
            f"https://reddit.com{post.permalink}\n"
        )
        if selftext:
            entry += f"\n{selftext}\n"
        results.append(entry)

    if not results:
        return f"No results for '{query}' in r/{subreddit}"
    header = f"**Search: '{query}' in r/{subreddit}** (sort={sort}, time={time_filter})\n\n"
    return header + "\n---\n".join(results)


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
    reddit = _reddit(ctx)
    limit = min(max(limit, 1), 25)
    sub = await reddit.subreddit(subreddit)

    if sort == "new":
        listing = sub.new(limit=limit)
    elif sort == "top":
        listing = sub.top(time_filter=time_filter, limit=limit)
    elif sort == "rising":
        listing = sub.rising(limit=limit)
    else:
        listing = sub.hot(limit=limit)

    results: list[str] = []
    async for post in listing:
        score = post.score
        comments = post.num_comments
        selftext = _truncate(post.selftext) if post.selftext else ""
        entry = (
            f"### {post.title}\n"
            f"{score} pts · {comments} comments · u/{post.author}\n"
            f"https://reddit.com{post.permalink}\n"
        )
        if selftext:
            entry += f"\n{selftext}\n"
        results.append(entry)

    if not results:
        return f"No posts found in r/{subreddit}"
    header = f"**r/{subreddit}** ({sort})\n\n"
    return header + "\n---\n".join(results)


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
    from asyncpraw.models import MoreComments

    reddit = _reddit(ctx)
    comment_limit = min(max(comment_limit, 1), 30)

    submission = await reddit.submission(url=url)
    submission.comment_sort = comment_sort
    await submission.load()

    header = (
        f"## {submission.title}\n"
        f"r/{submission.subreddit} · {submission.score} pts · "
        f"{submission.num_comments} comments · u/{submission.author}\n\n"
    )
    body = ""
    if submission.selftext:
        body = _truncate(submission.selftext, 2000) + "\n\n"

    comments_text = "### Comments\n\n"
    count = 0
    for comment in submission.comments:
        if isinstance(comment, MoreComments):
            continue
        if count >= comment_limit:
            break
        score = comment.score
        author = comment.author or "[deleted]"
        text = _truncate(comment.body, 400)
        comments_text += f"**u/{author}** ({score} pts)\n{text}\n\n"
        count += 1

    return header + body + comments_text
