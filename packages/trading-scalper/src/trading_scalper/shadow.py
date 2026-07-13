"""Shadow-mode telemetry recorder: raw tape capture + live VolumeProfile/VolumeRate.

Wired to the feed, written to disk, **read by nothing in the decision path** — the same
record-never-act posture as the B4 ``SignalLog``. The goal is to accumulate the data to
settle the open #1 "runaway-gap" (does a break into an LVN void vs a thick HVN predict a
runner?) *from evidence*, since it can't be backtested: the persister only ever kept
fills, never the raw tape, so 6/24 and 6/29 can't be rebuilt. So: capture forward.

Two artifacts under ``~/.trading/scalp/paper/``:

- ``{date}-tape.jsonl``   — every **underlying** timesale print (price/size/bid/ask/ms).
  The raw substrate: any VAP can be rebuilt offline with different buckets/thresholds,
  so a wrong guess today costs nothing. Buffered in memory and flushed on the snapshot
  timer, so the high-frequency tape doesn't cost a syscall per print.
- ``{date}-shadow.jsonl`` — a periodic POC / value-area + volume-rate snapshot per
  underlying (the *live read*). Lean, because the full histogram is rebuildable from
  the tape.

Observers are keyed to the subscribed symbol(s) — the traded future(s). Any print for a
symbol we didn't subscribe is ignored here; VAP is a property of the instrument's own
price structure.
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from trading_clients.market_stream import TimeSale

from trading_scalper.ports import MarketDataFeed
from trading_scalper.volume import VolumeProfile, VolumeRate

_PAPER_ROOT = Path.home() / ".trading" / "scalp" / "paper"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_tape_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}-tape.jsonl"


def default_shadow_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}-shadow.jsonl"


class ShadowRecorder:
    """Per-underlying volume observers + raw-tape capture, snapshotting on a timer.

    Attach to a feed with :meth:`attach`; run its flush/snapshot loop alongside the
    feed and persister in the CLI's ``asyncio.gather``. It only ever *writes* — no
    method returns anything a detector or broker reads.
    """

    def __init__(
        self,
        symbols: list[str],
        *,
        tape_path: Path,
        shadow_path: Path,
        bucket: float = 0.10,
        interval: float = 30.0,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._symbols = list(symbols)
        self.tape_path = Path(tape_path)
        self.shadow_path = Path(shadow_path)
        self._interval = interval
        self._clock = clock
        self.profiles = {s: VolumeProfile(bucket=bucket) for s in self._symbols}
        self.rates = {s: VolumeRate() for s in self._symbols}
        self._last_price: dict[str, float] = {}
        self._tape_buf: list[str] = []

    def attach(self, feed: MarketDataFeed) -> None:
        feed.on_timesale(self.on_timesale)

    def on_timesale(self, ts: TimeSale) -> None:
        if ts.symbol not in self.profiles:
            return  # an unsubscribed symbol — VAP is built only for the traded instrument(s)
        self.profiles[ts.symbol].add(ts.price, ts.size)
        self.rates[ts.symbol].add(ts.size, ts.ms)
        self._last_price[ts.symbol] = ts.price
        self._tape_buf.append(
            json.dumps(
                {
                    "symbol": ts.symbol,
                    "price": ts.price,
                    "size": ts.size,
                    "bid": ts.bid,
                    "ask": ts.ask,
                    "ms": ts.ms,
                }
            )
        )

    def flush_tape(self) -> None:
        """Append the buffered raw tape rows, then clear the buffer."""
        if not self._tape_buf:
            return
        self.tape_path.parent.mkdir(parents=True, exist_ok=True)
        with self.tape_path.open("a") as f:
            f.write("\n".join(self._tape_buf) + "\n")
        self._tape_buf.clear()

    def write_snapshots(self) -> None:
        """Append one POC/value-area + volume-rate snapshot per underlying that has traded."""
        rows = []
        now = self._clock()
        for sym in self._symbols:
            profile = self.profiles[sym]
            if profile.total <= 0:
                continue  # nothing traded yet — no profile to snapshot
            rows.append(
                {
                    "ts": now,
                    "symbol": sym,
                    "last": self._last_price.get(sym),
                    **profile.snapshot(),
                    **self.rates[sym].snapshot(),
                }
            )
        if not rows:
            return
        self.shadow_path.parent.mkdir(parents=True, exist_ok=True)
        with self.shadow_path.open("a") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    async def run(self) -> None:
        """Flush the tape buffer + write snapshots every ``interval`` s; once on shutdown."""
        try:
            while True:
                await asyncio.sleep(self._interval)
                self.flush_tape()
                self.write_snapshots()
        finally:
            self.flush_tape()
            self.write_snapshots()
