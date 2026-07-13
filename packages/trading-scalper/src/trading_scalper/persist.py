"""PaperPersister: write the paper broker's fills + a P&L summary to disk.

Goal 3 of the redesign — make the detector's paper track record reviewable after
a session. Two artifacts under ``~/.trading/scalp/paper/``:

- ``{date}.jsonl``        — one row per fill, appended as it happens (the trade log).
- ``{date}-summary.json`` — realized P&L + open positions, **recomputed from the
  fills log** (not live broker state) so it survives a mid-session daemon restart,
  rewritten periodically and once more on shutdown.

The summary is derived from the durable ``.jsonl``, not the in-memory broker,
because a **regime remap restarts the daemon** (a new contract needs a fresh
subscribe). The fills log is append-only and date-keyed, so it accumulates across
that restart; live process state (the broker ledger, the fill counter) does not.
Reading the broker would silently drop the prior process's fills — the 6/16 bug
where the summary reported +$770 / 64 fills while the log held the true ≈ +$589 /
88 fills (the morning's −$181 fade had been dropped). See ``summarize_fills``.

It only *reads* the broker (``realized_pnl`` / ``positions``) and listens to the
order-event stream; it never places an order.

A third artifact, ``{date}-signals.jsonl``, is written by ``SignalLog`` — one row
per *detector fire* (the B4 velocity/absorption telemetry), independent of fills:
a fire is logged even when it produces no paper fill (an alert-only level, or a
confirmed setup whose futures spread was too wide to model). The metadata is about
the *setup at fire time*, not an eventual fill, so it isn't gated on a FILLED event.

The two logs are joinable: a fire that places a bracket stamps the bracket's
entry-order id as ``bracket_id`` on its signal row, and every fill of that bracket
carries the same ``bracket_id`` in ``{date}.jsonl`` (with the close's ``realized_delta``
as the win/loss label). So the paper run's *features* (per fire) join cleanly to
their *outcome* (per close) on ``bracket_id`` — the labeled dataset a later
calibration step needs, with no fragile contract+timestamp reconstruction.
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from trading_scalper.domain import FireRecord, OrderEvent, OrderStatus, Side
from trading_scalper.ports import BrokerExecution
from trading_scalper.version import __version__

_PAPER_ROOT = Path.home() / ".trading" / "scalp" / "paper"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def summarize_fills(fills_path: Path) -> dict[str, object]:
    """Recompute realized P&L, fill count, and net open positions from the fills log.

    The fills JSONL is the session's durable, append-only truth — it accumulates
    across a daemon restart (a regime remap re-subscribes a new contract in a fresh
    process), whereas live process state resets each restart. So the summary is
    derived from the log, not the broker; otherwise a remap day drops the prior
    process's fills (the 6/16 +$770/64 vs the true ≈+$589/88).

    Realized P&L sums each fill's ``realized_delta`` (0 on an open, the close's
    dollars on the exit) — correct no matter how many processes wrote the log. Open
    positions are the net signed quantity per symbol (BUY +, SELL −). A missing log
    (no fills yet) summarizes to zeros.
    """
    realized = 0.0
    n_fills = 0
    net: dict[str, int] = {}
    if fills_path.exists():
        for line in fills_path.read_text().splitlines():
            if not line.strip():
                continue  # tolerate a blank/partial tail line from a hard kill
            row = json.loads(line)
            n_fills += 1
            delta = row.get("realized_delta")
            if delta is not None:
                realized += delta
            qty = row.get("qty") or 0
            net[row["symbol"]] = net.get(row["symbol"], 0) + (
                qty if row.get("side") == Side.BUY else -qty
            )
    return {
        "realized_pnl": round(realized, 2),
        "positions": [{"symbol": s, "qty": q} for s, q in net.items() if q != 0],
        "n_fills": n_fills,
    }


def default_fills_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}.jsonl"


def default_summary_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}-summary.json"


def default_signals_path(date: str, root: Path = _PAPER_ROOT) -> Path:
    return root / f"{date}-signals.jsonl"


class SignalLog:
    """Append one JSONL row per detector fire — the B4 velocity/absorption telemetry.

    The detector calls ``record`` on every confirmed fire; this stamps a wall-clock
    ``ts`` and the detector ``version`` and writes the row. Recorded, never gated —
    the row carries the metrics next to the setup identity so the paper run can later
    mine which of them separate winners from losers without any of them yet vetoing a
    setup. The ``version`` stamp is the scorecard's cohort key: it lets each session's
    logs self-describe which bot produced them, so grading pools only trades from the
    same behavior cohort (see ``version.py`` and ``scorecard.py``).
    """

    def __init__(self, path: Path, *, clock: Callable[[], str] = _now) -> None:
        self.path = Path(path)
        self._clock = clock
        self.n_fires = 0

    def record(self, rec: FireRecord) -> None:
        self.n_fires += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": self._clock(),
            "version": __version__,  # cohort key for the scorecard (version.py)
            "symbol": rec.symbol,
            "level": rec.level,
            "side": rec.side,
            "mode": rec.mode,
            "confirming": rec.confirming,
            "price": rec.price,
            "contract": rec.contract,
            "bracket_id": rec.bracket_id,  # join key → the bracket's fills (None if no fill)
            "velocity": round(rec.velocity, 4) if rec.velocity is not None else None,
            "cum_confirming_size": rec.cum_confirming_size,
            "cum_contrary_size": rec.cum_contrary_size,
            "book_imbalance": rec.book_imbalance,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")


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
        self._date = date
        self.fills_path = Path(fills_path)
        self.summary_path = Path(summary_path)
        self._interval = interval
        self._clock = clock
        broker.on_order_event(self._on_event)  # listen only — never read live broker state

    def _on_event(self, ev: OrderEvent) -> None:
        if ev.status is not OrderStatus.FILLED:
            return
        self.fills_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": self._clock(),
            "order_id": ev.order_id,
            "bracket_id": ev.bracket_id,  # the open this fill belongs to (join key)
            "symbol": ev.symbol,
            "side": ev.side.value,
            "qty": ev.filled_quantity,
            "fill_price": ev.fill_price,
            "realized_delta": (
                round(ev.realized_delta, 2) if ev.realized_delta is not None else None
            ),  # win/loss label: 0 on the open, the close's P&L on the exit
        }
        with self.fills_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def write_summary(self) -> None:
        """Snapshot realized P&L + open positions, recomputed from the fills log.

        Reads the durable ``.jsonl`` (via ``summarize_fills``) rather than live
        broker state, so the summary stays correct across a mid-session daemon
        restart — see this module's docstring for the 6/16 remap bug it fixes.
        """
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "date": self._date,
            "generated_at": self._clock(),
            **summarize_fills(self.fills_path),
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
