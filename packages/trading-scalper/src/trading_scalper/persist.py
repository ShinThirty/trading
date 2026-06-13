"""PaperPersister: write the paper broker's fills + a P&L summary to disk.

Goal 3 of the redesign — make the detector's paper track record reviewable after
a session. Two artifacts under ``~/.trading/scalp/paper/``:

- ``{date}.jsonl``        — one row per fill, appended as it happens (the trade log).
- ``{date}-summary.json`` — realized P&L + open positions, rewritten periodically
  and once more on shutdown.

It only *reads* the broker (``realized_pnl`` / ``positions``) and listens to the
order-event stream; it never places an order.
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from trading_scalper.domain import OrderEvent, OrderStatus
from trading_scalper.ports import BrokerExecution

_PAPER_ROOT = Path.home() / ".trading" / "scalp" / "paper"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_fills_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}.jsonl"


def default_summary_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}-summary.json"


class PaperPersister:
    """Appends fills to a JSONL log and snapshots a P&L summary on a timer."""

    def __init__(
        self,
        broker: BrokerExecution,
        *,
        date: str,
        fills_path: Path,
        summary_path: Path,
        interval: float = 30.0,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._broker = broker
        self._date = date
        self.fills_path = Path(fills_path)
        self.summary_path = Path(summary_path)
        self._interval = interval
        self._clock = clock
        self._n_fills = 0
        broker.on_order_event(self._on_event)

    def _on_event(self, ev: OrderEvent) -> None:
        if ev.status is not OrderStatus.FILLED:
            return
        self._n_fills += 1
        self.fills_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": self._clock(),
            "order_id": ev.order_id,
            "symbol": ev.symbol,
            "side": ev.side.value,
            "qty": ev.filled_quantity,
            "fill_price": ev.fill_price,
        }
        with self.fills_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def write_summary(self) -> None:
        """Snapshot realized P&L + open positions to the summary file."""
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "date": self._date,
            "generated_at": self._clock(),
            "realized_pnl": round(self._broker.realized_pnl(), 2),
            "positions": [
                {"symbol": p.symbol, "qty": p.quantity} for p in self._broker.positions()
            ],
            "n_fills": self._n_fills,
        }
        self.summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    async def run(self) -> None:
        """Rewrite the summary every ``interval`` seconds; flush once on shutdown."""
        try:
            while True:
                await asyncio.sleep(self._interval)
                self.write_summary()
        finally:
            self.write_summary()
