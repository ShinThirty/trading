"""Alpha Vantage API endpoint definitions with typed request/response models."""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.table_helpers import fmt_large, fmt_number, list_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class SentimentRequest(ParamsRequest):
    tickers: str | None = None
    topics: str | None = None
    sort: str = "LATEST"
    limit: int = 10

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "function": "NEWS_SENTIMENT",
            "sort": self.sort,
            "limit": str(self.limit),
        }
        if self.tickers:
            params["tickers"] = self.tickers
        if self.topics:
            params["topics"] = self.topics
        return params


@dataclass
class MoversRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {"function": "TOP_GAINERS_LOSERS"}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class SentimentResponse:
    articles: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "SentimentResponse":
        return cls(articles=data or [])

    def to_output(self) -> str:
        if not self.articles:
            return "(no articles)"
        rows = [
            {
                "Date": a.get("time_published", "")[:16],
                "Title": (a.get("title", "") or "")[:80],
                "Source": a.get("source", ""),
                "Sentiment": fmt_number(a.get("overall_sentiment_score"), 3),
                "Label": a.get("overall_sentiment_label", ""),
            }
            for a in self.articles
        ]
        return list_table(rows)


@dataclass
class MoversResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "MoversResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        if not self.data:
            return "(no data)"
        sections = []
        for key, title in [
            ("top_gainers", "Top Gainers"),
            ("top_losers", "Top Losers"),
            ("most_actively_traded", "Most Active"),
        ]:
            items = self.data.get(key, [])
            if items:
                rows = [
                    {
                        "Ticker": m.get("ticker", ""),
                        "Price": m.get("price", ""),
                        "Change": m.get("change_amount", ""),
                        "Change %": m.get("change_percentage", ""),
                        "Volume": fmt_large(m.get("volume")),
                    }
                    for m in items[:10]
                ]
                sections.append(f"### {title}\n\n{list_table(rows)}")
        return "\n\n".join(sections) if sections else "(no data)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

SENTIMENT = Endpoint(
    "",  # Alpha Vantage uses single URL with function param
    cache_ttl=3600,
    response_model=SentimentResponse,
    extract=lambda d: d.get("feed", []),
)

MOVERS = Endpoint(
    "",  # Alpha Vantage uses single URL with function param
    cache_ttl=900,
    response_model=MoversResponse,
)
