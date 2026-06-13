"""Core value types for the scalper: orders, positions, fills, and trade proposals.

Pure data — no I/O, no broker, no feed. The ``PaperBroker`` matching engine and
the ``SetupDetector`` are built entirely on these and are fully unit-testable
without a live broker or feed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

type OrderId = str


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Order:
    """An order request. ``quantity`` is always positive; ``side`` carries direction."""

    symbol: str
    side: Side
    quantity: int
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None

    def signed_delta(self) -> int:
        """Net position change in contracts if fully filled (+long / -short)."""
        return self.quantity if self.side is Side.BUY else -self.quantity


@dataclass(frozen=True, slots=True)
class Position:
    """A net position in one symbol. ``quantity`` is signed: +long / -short contracts."""

    symbol: str
    quantity: int


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """A push update from the broker: an order changed status (e.g. filled)."""

    order_id: OrderId
    symbol: str
    side: Side
    status: OrderStatus
    quantity: int
    filled_quantity: int = 0
    fill_price: float | None = None


type OrderEventCallback = Callable[[OrderEvent], None]


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """A detector-blessed entry: BUY-to-open ``contract`` with a premium-% bracket.

    The child stop-loss rests at ``entry * (1 - stop_pct)`` and the take-profit at
    ``entry * (1 + target_pct)`` (entry = the option's fill price), mirroring the
    native Webull bracket the paper run is validating. ``reason`` is the human-
    readable alert text that triggered it.
    """

    contract: str  # OCC option symbol to buy
    quantity: int
    stop_pct: float
    target_pct: float
    reason: str = ""
