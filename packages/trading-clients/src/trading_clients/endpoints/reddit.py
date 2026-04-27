"""Reddit JSON API endpoint definitions (no auth required)."""

from dataclasses import dataclass
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
            "best": "confidence", "top": "top", "new": "new",
            "controversial": "controversial", "old": "old", "qa": "qa",
        }
        return {
            "sort": sort_map.get(self.comment_sort, "confidence"),
            "limit": str(min(max(self.comment_limit, 1), 30)),
        }


# ── Response models ────────────────────────────────────────


def _format_post(post: dict, include_subreddit: bool = True) -> str:
    title = post.get("title", "")
    score = post.get("score", 0)
    comments = post.get("num_comments", 0)
    author = post.get("author", "[deleted]")
    permalink = post.get("permalink", "")
    selftext = _truncate(post.get("selftext", ""), 500) if post.get("selftext") else ""
    prefix = f"r/{post.get('subreddit', '')} · " if include_subreddit else ""
    entry = (
        f"### {title}\n"
        f"{prefix}{score} pts · {comments} comments · u/{author}\n"
        f"https://reddit.com{permalink}\n"
    )
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
            comments.append({
                "author": author,
                "score": cd.get("score", 0),
                "body": _truncate(cd.get("body", ""), 400),
            })
        return cls(
            title=post.get("title", ""),
            subreddit=post.get("subreddit", ""),
            score=post.get("score", 0),
            num_comments=post.get("num_comments", 0),
            author=post.get("author", "[deleted]"),
            selftext=_truncate(post.get("selftext", ""), 2000) if post.get("selftext") else "",
            comments=comments,
        )

    def to_output(self) -> str:
        header = (
            f"## {self.title}\n"
            f"r/{self.subreddit} · {self.score} pts · "
            f"{self.num_comments} comments · u/{self.author}\n\n"
        )
        body = f"{self.selftext}\n\n" if self.selftext else ""
        comments_text = "### Comments\n\n"
        for c in self.comments:
            comments_text += f"**u/{c['author']}** ({c['score']} pts)\n{c['body']}\n\n"
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
