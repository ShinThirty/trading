"""Reddit JSON API endpoint definitions (no auth required)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ── Request models ─────────────────────────────────────────


@dataclass
class SearchRequest(ParamsRequest, PathRequest):
    query: str
    subreddit: str = "all"
    sort: str = "relevance"
    time_filter: str = "week"
    limit: int = 10

    def to_path_params(self) -> dict[str, str]:
        return {"subreddit": self.subreddit}

    def to_params(self) -> dict[str, str]:
        return {
            "q": self.query,
            "sort": self.sort,
            "t": self.time_filter,
            "restrict_sr": "on",
            "limit": str(min(max(self.limit, 1), 25)),
        }


@dataclass
class SubredditRequest(ParamsRequest, PathRequest):
    subreddit: str
    sort: str = "hot"
    time_filter: str = "week"
    limit: int = 10

    def to_path_params(self) -> dict[str, str]:
        return {"subreddit": self.subreddit, "sort": self.sort}

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {"limit": str(min(max(self.limit, 1), 25))}
        if self.sort == "top":
            params["t"] = self.time_filter
        return params


@dataclass
class PostRequest(ParamsRequest, PathRequest):
    post_id: str
    comment_limit: int = 15
    comment_sort: str = "best"

    def to_path_params(self) -> dict[str, str]:
        return {"post_id": self.post_id}

    def to_params(self) -> dict[str, str]:
        sort_map = {
            "best": "confidence",
            "top": "top",
            "new": "new",
            "controversial": "controversial",
            "old": "old",
            "qa": "qa",
        }
        return {
            "sort": sort_map.get(self.comment_sort, "confidence"),
            "limit": str(min(max(self.comment_limit, 1), 30)),
        }


# ── Response models ────────────────────────────────────────


def _time_ago(epoch: float) -> str:
    delta = datetime.now(UTC) - datetime.fromtimestamp(epoch, UTC)
    seconds = int(delta.total_seconds())
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _format_post(post: dict, include_subreddit: bool = True) -> str:
    title = post.get("title", "")
    score = post.get("score", 0)
    comments = post.get("num_comments", 0)
    author = post.get("author", "[deleted]")
    permalink = post.get("permalink", "")
    selftext = _truncate(post.get("selftext", ""), 500) if post.get("selftext") else ""
    prefix = f"r/{post.get('subreddit', '')} · " if include_subreddit else ""
    age = _time_ago(post["created_utc"]) if post.get("created_utc") else ""
    ratio = post.get("upvote_ratio")
    flair = post.get("link_flair_text")
    link_url = post.get("url_overridden_by_dest", "")

    meta_parts = [f"{score} pts ({ratio:.0%} upvoted)" if ratio else f"{score} pts"]
    meta_parts.append(f"{comments} comments")
    meta_parts.append(f"u/{author}")
    if age:
        meta_parts.append(age)
    entry = f"### {title}\n"
    if flair:
        entry += f"[{flair}] "
    entry += f"{prefix}{' · '.join(meta_parts)}\n"
    entry += f"https://reddit.com{permalink}\n"
    if link_url and not post.get("is_self"):
        entry += f"{link_url}\n"
    if selftext:
        entry += f"\n{selftext}\n"
    return entry


@dataclass
class ListingResponse:
    posts: list[dict]

    @classmethod
    def from_response(cls, data: Any) -> "ListingResponse":
        children = data.get("data", {}).get("children", [])
        return cls(posts=[c["data"] for c in children if c.get("kind") == "t3"])

    def to_output(self, include_subreddit: bool = True) -> str:
        return "\n---\n".join(
            _format_post(p, include_subreddit=include_subreddit) for p in self.posts
        )


@dataclass
class PostResponse:
    title: str
    subreddit: str
    score: int
    num_comments: int
    author: str
    selftext: str
    upvote_ratio: float | None
    created_utc: float | None
    flair: str | None
    link_url: str | None
    comments: list[dict]

    @classmethod
    def from_response(cls, data: Any) -> "PostResponse":
        post = data[0]["data"]["children"][0]["data"]
        raw_comments = data[1]["data"]["children"]
        comments = []
        for c in raw_comments:
            if c.get("kind") != "t1":
                continue
            cd = c["data"]
            author = cd.get("author", "[deleted]")
            if author == "VisualMod":
                continue
            comments.append(
                {
                    "author": author,
                    "score": cd.get("score", 0),
                    "body": _truncate(cd.get("body", ""), 400),
                    "created_utc": cd.get("created_utc"),
                }
            )
        link_url = post.get("url_overridden_by_dest", "")
        return cls(
            title=post.get("title", ""),
            subreddit=post.get("subreddit", ""),
            score=post.get("score", 0),
            num_comments=post.get("num_comments", 0),
            author=post.get("author", "[deleted]"),
            selftext=_truncate(post.get("selftext", ""), 2000) if post.get("selftext") else "",
            upvote_ratio=post.get("upvote_ratio"),
            created_utc=post.get("created_utc"),
            flair=post.get("link_flair_text"),
            link_url=link_url if link_url and not post.get("is_self") else None,
            comments=comments,
        )

    def to_output(self) -> str:
        meta_parts = []
        if self.upvote_ratio:
            meta_parts.append(f"{self.score} pts ({self.upvote_ratio:.0%} upvoted)")
        else:
            meta_parts.append(f"{self.score} pts")
        meta_parts.append(f"{self.num_comments} comments")
        meta_parts.append(f"u/{self.author}")
        if self.created_utc:
            meta_parts.append(_time_ago(self.created_utc))

        header = f"## {self.title}\n"
        if self.flair:
            header += f"[{self.flair}] "
        header += f"r/{self.subreddit} · {' · '.join(meta_parts)}\n"
        if self.link_url:
            header += f"{self.link_url}\n"
        header += "\n"

        body = f"{self.selftext}\n\n" if self.selftext else ""
        comments_text = "### Comments\n\n"
        for c in self.comments:
            age = f" · {_time_ago(c['created_utc'])}" if c.get("created_utc") else ""
            comments_text += f"**u/{c['author']}** ({c['score']} pts{age})\n{c['body']}\n\n"
        return header + body + comments_text


# ── Endpoint definitions ───────────────────────────────────

SEARCH = Endpoint(
    path="/r/{subreddit}/search.json",
    cache_ttl=60,
    response_model=ListingResponse,
)

SUBREDDIT = Endpoint(
    path="/r/{subreddit}/{sort}.json",
    cache_ttl=60,
    response_model=ListingResponse,
)

POST = Endpoint(
    path="/comments/{post_id}.json",
    cache_ttl=300,
    response_model=PostResponse,
)
