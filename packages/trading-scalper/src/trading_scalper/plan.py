"""The session plan — the morning's blessed levels, in structured form.

`/scalp prep` writes a dated YAML at ``~/.trading/scalp/{date}-{symbol}.yaml``;
the daemon reads it. A plan is valid for exactly one day, so it's a flat file,
not a DB row — human-readable and hand-editable (nudge an edge before the open).

``PlanStore`` loads today's file and **hot-reloads on change** (re-run `/scalp
prep` and the daemon picks up the new plan on the next read). A missing file
degrades gracefully to ``None`` — the detector goes silent.

Note: ``levels`` are *underlying* prices that drive ``SetupDetector`` (which
watches the underlying). Each level optionally names the *option* ``contract`` to
buy when it tags; the paper bracket's stop/target are a percent of the option
premium (``default_stop_pct`` / ``target_pct``), so ``level.stop`` (an underlying
price) is alert-text only. Each level also carries a ``mode`` — ``fade``
(touch-and-reject, the positive-GEX setup) or ``break`` (cross-and-follow-through,
the negative-GEX setup) — which the detector uses to pick its trigger geometry.

``zero_gamma`` is the prep-time gamma-flip price (one per session). It is *not* a
tradeable level — the detector watches the underlying cross it and fires a
non-trading "re-run /scalp prep, the regime may be inverting" alert. The detector
never recomputes GEX (the stream carries no OI/greeks), so this stays the static
prep-time number; a cross means *reassess*, not an automatic fade↔break switch.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_SCALP_ROOT = Path.home() / ".trading" / "scalp"


@dataclass(frozen=True, slots=True)
class Level:
    price: float
    side: str  # "support" | "resistance"
    stop: float
    contract: str | None = None  # OCC option symbol to BUY when this level tags
    mode: str = "fade"  # "fade" (touch + reject) | "break" (cross + follow-through)


@dataclass(frozen=True, slots=True)
class SessionPlan:
    date: str
    symbol: str
    regime: str
    lean: str  # "long-only" | "short-only" | "both" | "no-trade"
    zero_gamma: float | None = None  # the prep-time gamma flip — tripwire, not a tradeable level
    levels: list[Level] = field(default_factory=list)
    default_stop_pct: float = 0.20  # child stop-loss = entry * (1 - pct)
    target_pct: float = 0.20  # child take-profit = entry * (1 + pct)
    contracts: int = 1  # quantity per setup
    max_trades: int | None = None
    daily_stop_usd: float | None = None
    notes: str = ""


def default_plan_path(symbol: str, date: str, root: Path = _SCALP_ROOT) -> Path:
    return root / f"{date}-{symbol}.yaml"


def load_session_plan(path: Path) -> SessionPlan:
    """Parse a session-plan YAML file into a ``SessionPlan`` (defensive defaults)."""
    data = yaml.safe_load(path.read_text()) or {}
    caps = data.get("session_caps") or {}
    levels = [
        Level(
            price=float(lvl["price"]),
            side=str(lvl["side"]),
            stop=float(lvl["stop"]),
            contract=(str(lvl["contract"]) if lvl.get("contract") else None),
            mode=str(lvl.get("mode", "fade")),
        )
        for lvl in (data.get("levels") or [])
    ]
    return SessionPlan(
        date=str(data.get("date", "")),
        symbol=str(data.get("symbol", "")),
        regime=str(data.get("regime", "")),
        lean=str(data.get("lean", "no-trade")),  # unspecified -> safest: don't alert
        zero_gamma=(float(data["zero_gamma"]) if data.get("zero_gamma") is not None else None),
        levels=levels,
        default_stop_pct=float(data.get("default_stop_pct", 0.20)),
        target_pct=float(data.get("target_pct", 0.20)),
        contracts=int(data.get("contracts", 1)),
        max_trades=caps.get("max_trades"),
        daily_stop_usd=caps.get("daily_stop_usd"),
        notes=str(data.get("notes", "")),
    )


class PlanStore:
    """Caches today's plan and reloads it when the file's mtime changes.

    Reloading is **crash-safe**: the plan is hand-edited mid-session, so a typo'd
    or half-written edit is caught, reported via ``on_error``, and the last-good
    plan is kept — the daemon keeps running on the prior map rather than dying on
    a bad parse. The mtime is advanced even on a failed parse so a persistently
    broken file isn't re-read on every read. The ``stat()`` is throttled to
    ``reload_interval`` seconds so a once-a-session edit isn't a syscall on every
    market tick (``current`` is called from the detector's per-tick hot path).
    """

    def __init__(
        self,
        path: Path,
        *,
        on_error: Callable[[str], None] | None = None,
        reload_interval: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = path
        self._on_error = on_error
        self._reload_interval = reload_interval
        self._clock = clock
        self._mtime: float | None = None
        self._plan: SessionPlan | None = None
        self._checked: float | None = None

    def current(self) -> SessionPlan | None:
        now = self._clock()
        if self._checked is not None and now - self._checked < self._reload_interval:
            return self._plan  # throttle: skip the stat() within the reload window
        self._checked = now
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._plan = None
            self._mtime = None
            return None
        if mtime != self._mtime:
            self._mtime = mtime  # advance first so a broken file doesn't re-parse every check
            try:
                self._plan = load_session_plan(self._path)
            except Exception as exc:  # a malformed hand-edit must not kill the daemon
                if self._on_error is not None:
                    self._on_error(
                        f"plan reload failed ({self._path.name}): {exc} — keeping the prior plan"
                    )
        return self._plan
