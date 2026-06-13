"""SetupDetector — prompts an entry when the underlying tags a blessed level.

On a *degraded* view (top-of-book + tape, no L2 ladder) it fires when the
underlying price tags one of the morning's blessed levels, filtered by the
plan's ``lean``, annotated with the tape direction. Each fire does two things:
it ``notify``s the human (the prompt), and — if that level names an option
``contract`` — emits a ``TradeProposal`` to ``propose`` so the paper broker can
auto-execute the same bracket. A level with no contract stays alert-only.

Hysteresis: a level fires once per tag — it re-arms only after price leaves the
band — so a price hovering on a level doesn't spam (one prompt + one paper
bracket per tag).

Inputs are the *underlying* feed (QQQ/SPY trades + timesales); the option
contract feed is what fills the bracket in the broker.
"""

from collections.abc import Callable

from trading_clients.market_stream import TimeSale, Trade

from trading_scalper.domain import TradeProposal
from trading_scalper.plan import Level, SessionPlan
from trading_scalper.ports import MarketDataFeed

_TAPE_PHRASE = {"buy": "tape lifting offers", "sell": "tape hitting bids", "mixed": "tape mixed"}


class SetupDetector:
    def __init__(
        self,
        plan_source: Callable[[], SessionPlan | None],
        notify: Callable[[str], None],
        propose: Callable[[TradeProposal], None] | None = None,
        *,
        tolerance: float = 0.10,
        rearm_margin: float = 0.05,
    ) -> None:
        self._plan_source = plan_source
        self._notify = notify
        self._propose = propose
        self._tolerance = tolerance
        self._rearm_margin = rearm_margin
        self._tape_side: dict[str, str] = {}
        self._active: set[tuple[float, str]] = set()  # (level.price, side) currently tagged

    def on_trade(self, trade: Trade) -> None:
        self._evaluate(trade.symbol, trade.price)

    def on_timesale(self, ts: TimeSale) -> None:
        self._tape_side[ts.symbol] = _tape_side(ts)
        self._evaluate(ts.symbol, ts.price)

    def _evaluate(self, symbol: str, price: float) -> None:
        plan = self._plan_source()
        if plan is None or plan.symbol != symbol:
            return
        for level in plan.levels:
            key = (level.price, level.side)
            distance = abs(price - level.price)
            if distance <= self._tolerance:
                if key not in self._active and _lean_allows(plan.lean, level.side):
                    self._active.add(key)
                    self._fire(plan, symbol, level)
            elif key in self._active and distance > self._tolerance + self._rearm_margin:
                self._active.discard(key)  # left the band -> re-arm this level

    def _fire(self, plan: SessionPlan, symbol: str, level: Level) -> None:
        """Prompt the human, and (if the level names a contract) propose the bracket."""
        message = self._message(symbol, level)
        self._notify(message)
        if level.contract and self._propose is not None:
            self._propose(
                TradeProposal(
                    contract=level.contract,
                    quantity=plan.contracts,
                    stop_pct=plan.default_stop_pct,
                    target_pct=plan.target_pct,
                    reason=message,
                )
            )

    def _message(self, symbol: str, level: Level) -> str:
        tape = _TAPE_PHRASE.get(self._tape_side.get(symbol, "mixed"), "tape mixed")
        return f"{symbol} tagged {level.price:g} {level.side} — {tape}; plan stop {level.stop:g}"


def _tape_side(ts: TimeSale) -> str:
    if ts.ask is not None and ts.price >= ts.ask:
        return "buy"  # printing at/above the offer — buyers lifting
    if ts.bid is not None and ts.price <= ts.bid:
        return "sell"  # printing at/below the bid — sellers hitting
    return "mixed"


def _lean_allows(lean: str, side: str) -> bool:
    if lean == "both":
        return True
    if lean == "long-only":
        return side == "support"
    if lean == "short-only":
        return side == "resistance"
    return False  # no-trade / unknown


def watch_setups(feed: MarketDataFeed, detector: SetupDetector) -> None:
    """Wire the underlying tape into the detector (trades + timesales)."""
    feed.on_trade(detector.on_trade)
    feed.on_timesale(detector.on_timesale)
