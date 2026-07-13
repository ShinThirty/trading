"""In-memory paper broker: a synthetic matching engine for forward-testing.

Zero I/O, in-memory only. A MARKET order fills immediately at the *marketable*
side of the book — the ask for a buy, the bid for a sell, so the paper entry
pays the spread the way a real marketable order would (falling back to the last
traded price seen via ``trade`` when there's no quote yet, or to an explicit
reference); a LIMIT / STOP order rests until a simulated tape print crosses it.
Every fill emits the same
``OrderEvent`` shape a real broker would push, so downstream consumers (the
``PaperPersister``) are broker-agnostic.

``place_bracket`` is the in-memory analog of a native broker bracket: it opens a
position at market and rests an OCO stop-loss / take-profit pair (a fill on one
cancels the other) — the thing the paper run is validating against Webull's
native 1st-Trigger bracket.

Position and realized-P&L bookkeeping is delegated to the ``Ledger`` primitive,
so ``net_position`` / ``realized_pnl`` stay the single verifiable place the math
lives.
"""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count

from trading_scalper.domain import (
    Order,
    OrderEvent,
    OrderId,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from trading_scalper.ledger import Ledger

_STOP_TYPES = (OrderType.STOP, OrderType.STOP_LIMIT)
_LIMIT_PRICED = (OrderType.LIMIT, OrderType.STOP_LIMIT)


def round_to_tick(price: float, tick: float) -> float:
    """Snap ``price`` to the nearest ``tick`` (e.g. 0.25 for /ES-family futures)."""
    if tick <= 0:
        return price
    return round(round(price / tick) * tick, 4)


def _crosses(order: Order, price: float) -> bool:
    """True if a tape print at ``price`` should fill this resting order."""
    if order.type in _STOP_TYPES:
        trigger = order.stop_price
        if trigger is None:
            return False
        return price >= trigger if order.side is Side.BUY else price <= trigger
    trigger = order.limit_price
    if trigger is None:
        return False
    return price <= trigger if order.side is Side.BUY else price >= trigger


@dataclass(slots=True)
class _Resting:
    order_id: OrderId
    order: Order
    bracket_id: OrderId | None = None  # entry-order id, when this leg belongs to a bracket


class PaperBroker:
    """A ``BrokerExecution`` backed by an in-memory matching engine."""

    def __init__(self, multiplier: float = 100, tick: float = 0.25) -> None:
        self._ids = count(1)
        self._ledger = Ledger(multiplier=multiplier)
        self._tick = tick
        self._last: dict[str, float] = {}
        self._book: dict[str, tuple[float | None, float | None]] = {}  # symbol -> (bid, ask)
        self._resting: dict[OrderId, _Resting] = {}
        self._oco: dict[OrderId, OrderId] = {}  # resting id -> its OCO sibling id
        self._callbacks: list[Callable[[OrderEvent], None]] = []

    # ── BrokerExecution ─────────────────────────────────────
    def place(self, order: Order, *, bracket_id: OrderId | None = None) -> OrderId:
        order_id = f"paper-{next(self._ids)}"
        if order.type is OrderType.MARKET:
            price = order.limit_price
            if price is None:
                price = self._marketable_price(order.symbol, order.side)
            if price is None:
                raise ValueError(
                    f"PaperBroker has no price for {order.symbol}; pass limit_price "
                    "as a reference or seed one via trade()"
                )
            self._fill(order_id, order, price, bracket_id=bracket_id)
        else:
            self._resting[order_id] = _Resting(order_id, order, bracket_id)
            self._emit(
                OrderEvent(
                    order_id,
                    order.symbol,
                    order.side,
                    OrderStatus.NEW,
                    order.quantity,
                    bracket_id=bracket_id,
                )
            )
        return order_id

    def place_bracket(
        self,
        symbol: str,
        direction: Side,
        quantity: int,
        *,
        stop_price: float,
        target_price: float,
        reference: float | None = None,
        tick: float | None = None,
    ) -> tuple[OrderId, OrderId, OrderId]:
        """Open ``quantity`` of ``symbol`` in ``direction`` at market and rest an OCO stop/target.

        Entry fills immediately at ``reference`` (or the marketable side of the book,
        falling back to the last tape print) — ``direction`` = ``BUY`` opens a long,
        ``SELL`` opens a short. Both children rest on the **opposite** side at the given
        absolute prices, snapped to ``tick``: for a long, a SELL-STOP below and a
        SELL-LIMIT above; for a short, a BUY-STOP above and a BUY-LIMIT below. The pair is
        OCO-linked (a fill on one cancels the other). Returns ``(entry_id, stop_id,
        target_id)``; ``entry_id`` doubles as the bracket's correlation key, stamped on
        every leg's ``OrderEvent`` so a closing fill joins back to the open.
        """
        entry_price = (
            reference if reference is not None else self._marketable_price(symbol, direction)
        )
        if entry_price is None:
            raise ValueError(
                f"PaperBroker has no price for {symbol}; pass reference or seed one via trade()"
            )
        exit_side = Side.SELL if direction is Side.BUY else Side.BUY
        entry_id = f"paper-{next(self._ids)}"
        entry = Order(symbol, direction, quantity, OrderType.MARKET, limit_price=entry_price)
        self._fill(entry_id, entry, entry_price, bracket_id=entry_id)

        grid = tick if tick is not None else self._tick
        stop_px = round_to_tick(stop_price, grid)
        target_px = round_to_tick(target_price, grid)
        stop_id = self.place(
            Order(symbol, exit_side, quantity, OrderType.STOP, stop_price=stop_px),
            bracket_id=entry_id,
        )
        target_id = self.place(
            Order(symbol, exit_side, quantity, OrderType.LIMIT, limit_price=target_px),
            bracket_id=entry_id,
        )
        self._oco[stop_id] = target_id
        self._oco[target_id] = stop_id
        return entry_id, stop_id, target_id

    def cancel(self, order_id: OrderId) -> None:
        resting = self._resting.pop(order_id, None)
        if resting is None:
            return
        self._oco.pop(order_id, None)
        o = resting.order
        self._emit(
            OrderEvent(
                order_id,
                o.symbol,
                o.side,
                OrderStatus.CANCELLED,
                o.quantity,
                bracket_id=resting.bracket_id,
            )
        )

    def positions(self) -> list[Position]:
        return [Position(s, self._ledger.net_qty(s)) for s in self._ledger.symbols()]

    def net_position(self, symbol: str) -> int:
        return self._ledger.net_qty(symbol)

    def realized_pnl(self) -> float:
        return self._ledger.realized

    def on_order_event(self, cb: Callable[[OrderEvent], None]) -> None:
        self._callbacks.append(cb)

    # ── synthetic tape (Phase 2 wires the live feed here) ───
    def quote(self, symbol: str, bid: float | None, ask: float | None) -> None:
        """Record top-of-book so a MARKET order fills at the marketable side.

        A quote never triggers a resting order — only a tape print (``trade``)
        crosses a STOP/LIMIT. This just lets the entry pay the spread instead of
        printing through it at the (better) last trade.
        """
        self._book[symbol] = (bid, ask)

    def trade(self, symbol: str, price: float) -> None:
        """Simulate a tape print: record the price and fill any order it crosses."""
        self._last[symbol] = price
        for order_id, resting in list(self._resting.items()):
            if order_id not in self._resting:
                continue  # already cancelled as an OCO sibling earlier this pass
            o = resting.order
            if o.symbol != symbol or not _crosses(o, price):
                continue
            del self._resting[order_id]
            if o.type in _LIMIT_PRICED and o.limit_price is not None:
                fill_price = o.limit_price
            else:
                fill_price = price
            self._fill(order_id, o, fill_price, bracket_id=resting.bracket_id)
            sibling = self._oco.pop(order_id, None)
            if sibling is not None:
                self._oco.pop(sibling, None)
                self.cancel(sibling)  # OCO: this leg filled, kill the other

    # ── internals ───────────────────────────────────────────
    def _marketable_price(self, symbol: str, side: Side) -> float | None:
        """Price a MARKET order crosses to: the ask for a buy, the bid for a sell
        (you pay the spread), falling back to the last print when there's no quote."""
        bid, ask = self._book.get(symbol, (None, None))
        quote = ask if side is Side.BUY else bid
        if quote is not None and quote > 0:
            return quote
        return self._last.get(symbol)

    def _fill(
        self, order_id: OrderId, order: Order, price: float, *, bracket_id: OrderId | None = None
    ) -> None:
        realized = self._ledger.record(order.symbol, order.side is Side.BUY, order.quantity, price)
        self._emit(
            OrderEvent(
                order_id,
                order.symbol,
                order.side,
                OrderStatus.FILLED,
                order.quantity,
                filled_quantity=order.quantity,
                fill_price=price,
                bracket_id=bracket_id,
                realized_delta=realized,
            )
        )

    def _emit(self, event: OrderEvent) -> None:
        for cb in self._callbacks:
            cb(event)
