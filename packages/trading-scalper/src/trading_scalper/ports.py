"""The two ports the scalper talks to: market data in, broker orders out.

Both are Protocols, so the discipline core stays broker- and feed-agnostic:
``PaperBroker`` satisfies ``BrokerExecution``; ``DxLinkFeed`` satisfies
``MarketDataFeed``. Nothing in the core imports a concrete client.

The feed payload types (``Quote`` / ``Trade`` / ``TimeSale``) are provider-neutral
value types defined in ``trading_clients.market_stream`` — produced by any feed,
so the port never sees a vendor-specific payload.
"""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from trading_clients.market_stream import Quote, TimeSale, Trade

from trading_scalper.domain import Order, OrderEventCallback, OrderId, Position


@runtime_checkable
class MarketDataFeed(Protocol):
    """Where prices come from: top-of-book quotes + the tape. No depth ladder."""

    async def subscribe(self, symbols: list[str]) -> None: ...
    def on_quote(self, cb: Callable[[Quote], None]) -> None: ...
    def on_trade(self, cb: Callable[[Trade], None]) -> None: ...
    def on_timesale(self, cb: Callable[[TimeSale], None]) -> None: ...


@runtime_checkable
class BrokerExecution(Protocol):
    """Orders out (place / cancel) plus account events in (on_order_event)."""

    def place(self, order: Order) -> OrderId: ...
    def cancel(self, order_id: OrderId) -> None: ...
    def positions(self) -> list[Position]: ...
    def net_position(self, symbol: str) -> int: ...
    def realized_pnl(self) -> float: ...  # session-to-date, dollars (cold-start reconcile + live)
    def on_order_event(self, cb: OrderEventCallback) -> None: ...
