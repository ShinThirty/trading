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
price) is alert-text only.
"""

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


@dataclass(frozen=True, slots=True)
class SessionPlan:
    date: str
    symbol: str
    regime: str
    lean: str  # "long-only" | "short-only" | "both" | "no-trade"
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
        )
        for lvl in (data.get("levels") or [])
    ]
    return SessionPlan(
        date=str(data.get("date", "")),
        symbol=str(data.get("symbol", "")),
        regime=str(data.get("regime", "")),
        lean=str(data.get("lean", "no-trade")),  # unspecified -> safest: don't alert
        levels=levels,
        default_stop_pct=float(data.get("default_stop_pct", 0.20)),
        target_pct=float(data.get("target_pct", 0.20)),
        contracts=int(data.get("contracts", 1)),
        max_trades=caps.get("max_trades"),
        daily_stop_usd=caps.get("daily_stop_usd"),
        notes=str(data.get("notes", "")),
    )


class PlanStore:
    """Caches today's plan and reloads it when the file's mtime changes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float | None = None
        self._plan: SessionPlan | None = None

    def current(self) -> SessionPlan | None:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._plan = None
            self._mtime = None
            return None
        if mtime != self._mtime:
            self._plan = load_session_plan(self._path)
            self._mtime = mtime
        return self._plan
