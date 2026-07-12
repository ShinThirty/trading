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
    """A push update from the broker: an order changed status (e.g. filled).

    ``bracket_id`` is the entry-order id shared by all three legs of a
    ``place_bracket`` (entry + OCO stop/target), so a closing fill can be tied
    back to the open that spawned it — and, via the matching ``FireRecord``, to
    the detector fire. ``realized_delta`` is the dollars this fill realized
    (0 for an opening fill, the ledger's per-close P&L for a reducing one): the
    recorded win/loss label, so the outcome never has to be re-derived offline.
    """

    order_id: OrderId
    symbol: str
    side: Side
    status: OrderStatus
    quantity: int
    filled_quantity: int = 0
    fill_price: float | None = None
    bracket_id: OrderId | None = None
    realized_delta: float | None = None


type OrderEventCallback = Callable[[OrderEvent], None]


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """A detector-blessed entry: open ``symbol`` in ``direction`` with a price bracket.

    The entry fills at market — ``direction`` = ``BUY`` opens a long, ``SELL`` opens a
    short (futures short freely; no put wrapper). The OCO children rest on the opposite
    side at **absolute** prices resolved upstream from the session plan: ``stop_price``
    (the bail level) and ``target_price`` (the take-profit). ``reason`` is the human-
    readable alert text that triggered it.
    """

    symbol: str  # the futures symbol to trade (e.g. "/MES")
    direction: Side  # BUY = open long, SELL = open short
    quantity: int
    stop_price: float
    target_price: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FireRecord:
    """Telemetry captured the instant a setup fires — **recorded, never a gate**.

    The B4 velocity/absorption signals (``velocity`` / ``cum_confirming_size`` /
    ``cum_contrary_size`` / ``book_imbalance``) are logged on *every* confirmed fire
    so the paper run can later mine which of them separate winners from losers.
    They do **not** influence whether the setup fires — that decision stays geometry
    + lean + tape. ``velocity`` is the signed underlying $/s over the trailing tape
    window (``None`` when fewer than two timestamped prints are in it); the cumulative
    sizes are summed tape volume over that same window, split by aggressor side
    relative to the setup's confirming direction; ``book_imbalance`` is the
    underlying top-of-book ``bid_size - ask_size`` at the fire (``None`` if unquoted).
    A wall-clock ``ts`` is stamped by the writer, not here, so the detector stays
    clock-free and deterministic. ``bracket_id`` is the **join key** to the
    realized outcome: the entry-order id of the paper bracket this fire placed
    (``None`` for an alert-only or spread-suppressed fire that produced no fill),
    matching the ``bracket_id`` carried on every fill of that bracket — so the
    paper run's features can be joined to their win/loss label without a fragile
    contract+timestamp heuristic.
    """

    symbol: str
    level: float  # the blessed level price
    side: str  # support | resistance
    mode: str  # fade | break | reversal | retest
    confirming: str  # buy | sell — the tape side that confirmed
    price: float  # underlying price at the fire
    contract: str | None  # the traded futures symbol, or None for an alert-only level
    bracket_id: OrderId | None  # entry-order id of the placed bracket (join key); None if no fill
    velocity: float | None
    cum_confirming_size: int
    cum_contrary_size: int
    book_imbalance: int | None
