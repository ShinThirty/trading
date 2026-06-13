"""Provider-neutral streaming market-data value types.

These are what a streaming feed emits, independent of vendor: a Tradier feed
and (later) a Tastytrade feed both parse their wire formats into these. The
scalper's ``MarketDataFeed`` port is typed in terms of them, so the discipline
core never sees a vendor-specific payload.

Top-of-book + tape only — there is no depth-ladder type here, by design (none
of the cheap streaming feeds expose L2).
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Quote:
    """Top-of-book bid/ask snapshot. ``ms`` is the freshest side's epoch-ms timestamp."""

    symbol: str
    bid: float | None
    ask: float | None
    bid_size: int | None = None
    ask_size: int | None = None
    ms: int | None = None


@dataclass(frozen=True, slots=True)
class Trade:
    """An executed print."""

    symbol: str
    price: float
    size: int | None = None
    ms: int | None = None


@dataclass(frozen=True, slots=True)
class TimeSale:
    """A tape entry in a continuous time slice. ``price`` is the slice's last trade."""

    symbol: str
    price: float
    size: int | None = None
    bid: float | None = None
    ask: float | None = None
    ms: int | None = None


type MarketEvent = Quote | Trade | TimeSale
