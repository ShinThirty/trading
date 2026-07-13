"""Cost-basis ledger: positions and realized P&L from a fill stream.

A pure, deterministic primitive — the single verifiable place all the
position-and-P&L arithmetic lives, so nothing downstream (the PaperBroker) does
ad hoc math. P&L is in dollars via the contract multiplier — the instrument's point
value, read off the exchange at resolution (see ``contract.py``), never typed in.
Fractional by type, not by accident: CME's micro Dow pays $0.50/pt.

Average-cost basis: a reducing fill realizes
``(exit - avg_cost) * closed_qty * multiplier``, signed by position direction; a
fill that flips through zero closes the old side and opens the remainder fresh
at the fill price.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class _Book:
    qty: int = 0  # signed contracts: +long / -short
    avg_cost: float = 0.0  # average entry, in price points


@dataclass(slots=True)
class Ledger:
    """Per-symbol cost basis + cumulative realized P&L (dollars)."""

    multiplier: float = 100
    realized: float = 0.0
    _books: dict[str, _Book] = field(default_factory=dict)

    def net_qty(self, symbol: str) -> int:
        book = self._books.get(symbol)
        return book.qty if book else 0

    def symbols(self) -> list[str]:
        """Symbols with a non-flat position."""
        return [s for s, b in self._books.items() if b.qty != 0]

    def seed(self, symbol: str, quantity: int, avg_cost: float) -> None:
        """Adopt a pre-existing position without realizing P&L (cold-start reconcile).

        For positions that exist before the session opens: set the book directly
        so a later close realizes against ``avg_cost``. Replaces any existing book;
        a zero quantity clears it.
        """
        if quantity == 0:
            self._books.pop(symbol, None)
        else:
            self._books[symbol] = _Book(qty=quantity, avg_cost=avg_cost)

    def record(self, symbol: str, is_buy: bool, quantity: int, price: float) -> float:
        """Apply a fill; return the realized-P&L delta (dollars) it produced."""
        book = self._books.setdefault(symbol, _Book())
        delta = quantity if is_buy else -quantity

        if book.qty == 0 or (book.qty > 0) == (delta > 0):
            # opening or adding in the same direction → weighted-average the cost
            total = abs(book.qty) + abs(delta)
            book.avg_cost = (book.avg_cost * abs(book.qty) + price * abs(delta)) / total
            book.qty += delta
            return 0.0

        # reducing / closing (possibly flipping through zero)
        closed = min(abs(delta), abs(book.qty))
        direction = 1 if book.qty > 0 else -1
        realized_delta = (price - book.avg_cost) * closed * self.multiplier * direction
        book.qty += delta
        if book.qty == 0:
            book.avg_cost = 0.0
        elif (book.qty > 0) != (direction > 0):
            # flipped through zero → the remainder is a fresh position at this price
            book.avg_cost = price
        self.realized += realized_delta
        return realized_delta
