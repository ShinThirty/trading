"""Shadow-mode recorder for the live future↔cash-index carry basis.

The futures level map is built from **cash-index** gamma walls (index points — SPX for
/MES, NDX for /MNQ; the reference symbol is the traded instrument's, see
``instruments.py``), then shifted into futures price by the carry basis —
``basis = future_price − index`` — which is pure cost-of-carry (financing − dividends),
converging to 0 at expiry and resetting at the quarterly roll. `/scalp` prep measures it
once to write the map; this records it *live* all session so a later call — bake a
per-session offset vs. track basis live in the detector's geometry — rests on recorded
evidence, not a guess.

**Read by nothing in the decision path** — same record-never-act posture as
``ShadowRecorder`` / the B4 ``SignalLog``. One artifact under ``~/.trading/scalp/paper/``:

- ``{date}-basis.jsonl`` — a periodic ``{future_price, reference_level, basis}`` snapshot.

Prices: the **future** is taken from the quote mid (falling back to the last trade); the
**reference index** from the last trade — the computed cash-index level prints as a Trade
during RTH — falling back to the quote mid. A snapshot is skipped until both sides have a
price.

**Only RTH rows are meaningful.** A cash index computes only while its components trade
(~09:30–16:00 ET); overnight and on Globex reopens the future is live but the index is
frozen at the prior cash close, so a basis snapshot then is carry *plus* the future's
off-hours drift, not clean carry. Rows are stamped ``ts`` (UTC) so the analysis filters
to the RTH window; the recorder deliberately doesn't gate on a clock (it stays a dumb,
testable observer).
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from trading_clients.market_stream import Quote, Trade

from trading_scalper.ports import MarketDataFeed

_PAPER_ROOT = Path.home() / ".trading" / "scalp" / "paper"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_basis_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}-basis.jsonl"


class BasisRecorder:
    """Tracks the latest future + reference price and snapshots their basis on a timer.

    Attach to a feed with :meth:`attach`; run its snapshot loop alongside the feed in
    the CLI's ``asyncio.gather``. It only ever *writes* — no method returns anything a
    detector or broker reads.
    """

    def __init__(
        self,
        future_symbol: str,
        reference_symbol: str,
        *,
        basis_path: Path,
        interval: float = 30.0,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._future = future_symbol
        self._reference = reference_symbol
        self.basis_path = Path(basis_path)
        self._interval = interval
        self._clock = clock
        self._mid: dict[str, float] = {}  # quote-derived (bid+ask)/2
        self._last: dict[str, float] = {}  # last trade print

    def attach(self, feed: MarketDataFeed) -> None:
        feed.on_quote(self.on_quote)
        feed.on_trade(self.on_trade)

    def on_quote(self, q: Quote) -> None:
        if q.symbol in (self._future, self._reference) and q.bid is not None and q.ask is not None:
            self._mid[q.symbol] = (q.bid + q.ask) / 2

    def on_trade(self, t: Trade) -> None:
        if t.symbol in (self._future, self._reference):
            self._last[t.symbol] = t.price

    def _future_price(self) -> float | None:
        mid = self._mid.get(self._future)
        return mid if mid is not None else self._last.get(self._future)

    def _reference_price(self) -> float | None:
        last = self._last.get(self._reference)
        return last if last is not None else self._mid.get(self._reference)

    def snapshot_row(self) -> dict[str, object] | None:
        """The current basis row, or ``None`` until both sides have a price."""
        fut = self._future_price()
        ref = self._reference_price()
        if fut is None or ref is None:
            return None
        return {
            "ts": self._clock(),
            "future": self._future,
            "future_price": fut,
            "reference": self._reference,
            "reference_level": ref,
            "basis": fut - ref,
        }

    def write_snapshot(self) -> None:
        row = self.snapshot_row()
        if row is None:
            return  # nothing to record until both legs have printed
        self.basis_path.parent.mkdir(parents=True, exist_ok=True)
        with self.basis_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    async def run(self) -> None:
        """Snapshot the basis every ``interval`` s; once more on shutdown."""
        try:
            while True:
                await asyncio.sleep(self._interval)
                self.write_snapshot()
        finally:
            self.write_snapshot()
