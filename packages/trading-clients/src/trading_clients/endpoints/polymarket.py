"""Polymarket Gamma API endpoint definitions.

Source: gamma-api.polymarket.com. No auth required for read-only event/market data.

Polymarket models markets as a parent **event** (e.g. "Fed Decision in June?")
containing several child binary markets, each scoped to a single outcome (e.g.
"25 bps decrease", "No change"). The yes-price on each child market IS the
implied probability of that outcome, since they're constructed as YES/NO
contracts on a single proposition.

Probability normalization: yes-prices across child markets typically sum close
to 1.0 but can drift slightly due to fee/spread distortion. We expose them as
reported and let the consumer renormalize if needed.
"""

import json
from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest
from trading_clients.endpoints.prediction_market import PredictionEvent, PredictionOutcome


@dataclass
class GetEventBySlugRequest(ParamsRequest):
    """Fetch a Polymarket event (with child markets) by URL slug.

    The slug is the URL-friendly key — e.g. `fed-decision-in-june-825` for
    https://polymarket.com/event/fed-decision-in-june-825.
    """

    slug: str

    def to_params(self) -> dict[str, str]:
        return {"slug": self.slug}


@dataclass
class ListEventsByTagRequest(ParamsRequest):
    """List Polymarket events under a tag, ordered by upcoming end date.

    tag_slug: Polymarket tag identifier (e.g. `fed`, `economy`, `elections`).
    limit: number of events to return.
    title_contains: optional case-insensitive substring filter applied client-side
        after the API response (Polymarket's filter param doesn't search title).
    """

    tag_slug: str
    limit: int = 20

    def to_params(self) -> dict[str, str]:
        return {
            "tag_slug": self.tag_slug,
            "closed": "false",
            "active": "true",
            "order": "endDate",
            "ascending": "true",
            "limit": str(self.limit),
        }


def _safe_json_list(raw: str | list | None) -> list:
    """Polymarket returns some array fields as JSON-encoded strings. Decode safely."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return []


def _to_float(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _polymarket_event_from_dict(event: dict) -> PredictionEvent:
    """Normalize a Polymarket event dict into PredictionEvent."""
    outcomes: list[PredictionOutcome] = []
    for m in event.get("markets", []):
        prices = _safe_json_list(m.get("outcomePrices"))
        labels = _safe_json_list(m.get("outcomes"))
        # Each child market is binary YES/NO on a single proposition.
        # The YES price IS the implied probability of the proposition.
        if not prices or not labels:
            continue
        yes_idx = None
        for i, lab in enumerate(labels):
            if isinstance(lab, str) and lab.strip().lower() == "yes":
                yes_idx = i
                break
        if yes_idx is None or yes_idx >= len(prices):
            continue
        yes_price = _to_float(prices[yes_idx])
        if yes_price is None:
            continue
        # groupItemTitle is the proposition (e.g. "No change"); fall back to question
        label = m.get("groupItemTitle") or m.get("question") or "?"
        outcomes.append(
            PredictionOutcome(
                label=label,
                implied_prob=yes_price,
                volume=_to_float(m.get("volume")),
                volume_24h=_to_float(m.get("volume24hr")),
                key=m.get("conditionId", "") or m.get("id", ""),
            )
        )
    outcomes.sort(key=lambda o: o.implied_prob, reverse=True)
    end_date = event.get("endDate", "") or ""
    return PredictionEvent(
        title=event.get("title", "") or "",
        key=event.get("slug", "") or "",
        end_date=end_date[:10] if end_date else "",
        source="polymarket",
        outcomes=outcomes,
    )


@dataclass
class PolymarketEventResponse:
    """A single Polymarket event normalized to PredictionEvent."""

    event: PredictionEvent

    @classmethod
    def from_response(cls, data) -> "PolymarketEventResponse":
        # /events?slug=... returns a list (filtered to one match for a slug)
        if isinstance(data, list):
            event = data[0] if data else {}
        elif isinstance(data, dict):
            event = data
        else:
            event = {}
        return cls(event=_polymarket_event_from_dict(event))

    def to_output(self) -> str:
        return self.event.to_output()


@dataclass
class PolymarketEventListResponse:
    """A list of Polymarket events normalized to PredictionEvent."""

    events: list[PredictionEvent]

    @classmethod
    def from_response(cls, data) -> "PolymarketEventListResponse":
        items = data if isinstance(data, list) else []
        return cls(events=[_polymarket_event_from_dict(e) for e in items])

    def to_output(self) -> str:
        if not self.events:
            return "(no events)"
        lines: list[str] = []
        for ev in self.events:
            lines.append(ev.to_output())
            lines.append("")
        return "\n".join(lines).rstrip()


# ─────────────────────────────────────────────────────────────────
# Endpoint definitions
# ─────────────────────────────────────────────────────────────────
# Cache TTL: 60s. Implied probs change continuously during trading hours;
# a short cache absorbs duplicate calls without serving stale data.

GET_EVENT_BY_SLUG = Endpoint(
    "/events",
    cache_ttl=60,
    response_model=PolymarketEventResponse,
)

LIST_EVENTS_BY_TAG = Endpoint(
    "/events",
    cache_ttl=300,
    response_model=PolymarketEventListResponse,
)
