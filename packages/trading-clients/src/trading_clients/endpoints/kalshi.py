"""Kalshi Elections API endpoint definitions.

Source: api.elections.kalshi.com (CFTC-regulated US event-contract exchange).
Read-only event/market data is publicly accessible without auth.

Kalshi's event taxonomy mirrors Polymarket's: a parent event (e.g.
`KXFED-26JUN`) bundles child markets that are individual binary YES/NO
contracts on a single proposition (e.g. "Above 3.50%"). The yes-side
mid price (or last_price) gives the implied probability.

Kalshi rate-decision events are typically structured as **CDF strikes**
("Above X%" for ascending X), so the implied probability of being IN a
specific bucket is the consecutive difference. We expose the raw markets
and let consumers do the decomposition where needed.
"""

from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest
from trading_clients.endpoints.prediction_market import PredictionEvent, PredictionOutcome


@dataclass
class GetEventByTickerRequest(ParamsRequest, PathRequest):
    """Fetch a Kalshi event with all child markets nested.

    event_ticker: Kalshi's ticker for the parent event (e.g. `KXFED-26JUN`).
    """

    event_ticker: str

    def to_path_params(self) -> dict[str, str]:
        return {"event_ticker": self.event_ticker}

    def to_params(self) -> dict[str, str]:
        return {"with_nested_markets": "true"}


def _to_float(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _kalshi_event_from_dict(event: dict) -> PredictionEvent:
    """Normalize a Kalshi event dict (with nested markets) into PredictionEvent."""
    outcomes: list[PredictionOutcome] = []
    for m in event.get("markets", []):
        bid = _to_float(m.get("yes_bid_dollars"))
        ask = _to_float(m.get("yes_ask_dollars"))
        last = _to_float(m.get("last_price_dollars"))
        # Mid-of-bid-ask is the cleanest implied probability when both sides
        # are present; fall back to last price if a side is missing/zero.
        if bid is not None and ask is not None and ask > 0:
            implied = (bid + ask) / 2.0
        elif last is not None and last > 0:
            implied = last
        elif ask is not None:
            implied = ask
        elif bid is not None:
            implied = bid
        else:
            continue
        label = m.get("yes_sub_title") or m.get("subtitle") or m.get("ticker") or "?"
        outcomes.append(
            PredictionOutcome(
                label=label,
                implied_prob=implied,
                bid=bid,
                ask=ask,
                volume=_to_float(m.get("volume")),
                volume_24h=_to_float(m.get("volume_24h")),
                key=m.get("ticker", "") or "",
            )
        )
    outcomes.sort(key=lambda o: o.implied_prob, reverse=True)
    end_date = event.get("expected_expiration_time", "") or event.get("close_time", "") or ""
    return PredictionEvent(
        title=event.get("title", "") or "",
        key=event.get("event_ticker", "") or "",
        end_date=end_date[:10] if end_date else "",
        source="kalshi",
        outcomes=outcomes,
    )


@dataclass
class KalshiEventResponse:
    """A single Kalshi event normalized to PredictionEvent."""

    event: PredictionEvent

    @classmethod
    def from_response(cls, data) -> "KalshiEventResponse":
        # /events/{event_ticker}?with_nested_markets=true returns {event: {...}}
        if isinstance(data, dict):
            event = data.get("event", {}) or data
        else:
            event = {}
        return cls(event=_kalshi_event_from_dict(event))

    def to_output(self) -> str:
        return self.event.to_output()


# ─────────────────────────────────────────────────────────────────
# Endpoint definitions
# ─────────────────────────────────────────────────────────────────
# Cache TTL: 60s — same reasoning as Polymarket (continuous price updates).

GET_EVENT_BY_TICKER = Endpoint(
    "/trade-api/v2/events/{event_ticker}",
    cache_ttl=60,
    response_model=KalshiEventResponse,
)
