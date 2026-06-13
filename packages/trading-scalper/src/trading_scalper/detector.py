"""SetupDetector — fires a confirmed entry when the underlying tags a blessed level.

On a *degraded* view (top-of-book + tape, no L2 ladder) it confirms a setup from
three things that are all already on the wire:

1. **Geometry** keyed to the level's ``mode``:
   - ``fade`` (positive-GEX setup): price touches within ``tolerance`` of the level
     — the mean-reversion trade at a gamma wall (touch-and-reject).
   - ``break`` (negative-GEX setup): price *crosses* the level by ``break_margin``
     in the trade's direction — the momentum trade (cross-and-follow-through).
2. **Lean** — the plan's ``lean`` must allow the trade *direction* (a call/long
   needs ``long-only`` or ``both``; a put/short needs ``short-only`` or ``both``).
3. **Tape** — the last timesale's aggressor side must agree with the option's
   direction (a call wants buyers lifting offers; a put wants sellers hitting
   bids). Direction is read from the level's ``contract`` (``parse_occ``); for an
   alert-only level it's derived from ``side`` + ``mode``.

Only a setup that clears all three fires — there is no bare-touch heads-up. The
fire ``notify``s the human and, if the level names a ``contract``, emits a
``TradeProposal`` so the paper broker auto-executes the same bracket. A
**spread gate** sits on the proposal only: a confirmed-but-wide option still
alerts (work a limit) but is not paper-filled, keeping the paper book's fills
honest. The underlying's top-of-book size imbalance is a soft annotation, never
a gate.

Hysteresis: ``_active`` is set only on a *confirmed* fire, so an unconfirmed tag
keeps re-evaluating in-zone until the tape turns, then fires once; it re-arms
when price leaves the zone. Tape direction comes from timesales, so a level seen
only by trades (no timesale) waits for a tape print before it can confirm.

Separately, the **zero-gamma tripwire** (``_check_flip``) watches the underlying
cross the plan's static flip price in *either* direction and fires a non-trading
"the regime may be inverting — re-run /scalp prep" alert. It is not gated on
lean/tape/contract and proposes nothing; it never recomputes GEX (the stream has
no OI/greeks) — it reuses the prep-time number, so a cross means *reassess*, not
an automatic fade↔break switch.
"""

from collections.abc import Callable

from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_clients.options import parse_occ

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
        break_margin: float = 0.05,
        spread_max_pct: float = 0.10,
        flip_margin: float = 0.10,
    ) -> None:
        self._plan_source = plan_source
        self._notify = notify
        self._propose = propose
        self._tolerance = tolerance
        self._rearm_margin = rearm_margin
        self._break_margin = break_margin
        self._spread_max_pct = spread_max_pct
        self._flip_margin = flip_margin
        self._tape_side: dict[str, str] = {}
        self._quotes: dict[str, Quote] = {}  # symbol -> latest top-of-book (underlying + options)
        self._active: set[tuple[float, str]] = set()  # (level.price, side) currently fired
        self._flip_side: dict[str, str] = {}  # symbol -> "above" | "below" the zero-gamma flip

    def on_quote(self, quote: Quote) -> None:
        self._quotes[quote.symbol] = quote

    def on_trade(self, trade: Trade) -> None:
        self._evaluate(trade.symbol, trade.price)

    def on_timesale(self, ts: TimeSale) -> None:
        self._tape_side[ts.symbol] = _tape_side(ts)
        self._evaluate(ts.symbol, ts.price)

    def _evaluate(self, symbol: str, price: float) -> None:
        plan = self._plan_source()
        if plan is None or plan.symbol != symbol:
            return
        self._check_flip(plan, symbol, price)
        tape = self._tape_side.get(symbol, "mixed")
        for level in plan.levels:
            key = (level.price, level.side)
            confirming = _confirming_side(level)
            if self._in_zone(level, price, confirming):
                if (
                    key not in self._active
                    and _lean_allows(plan.lean, confirming)
                    and tape == confirming
                ):
                    self._active.add(key)
                    self._fire(plan, symbol, level)
            elif key in self._active and self._cleared(level, price, confirming):
                self._active.discard(key)  # left the zone -> re-arm this level

    def _check_flip(self, plan: SessionPlan, symbol: str, price: float) -> None:
        """Zero-gamma tripwire — a *non-trading* 'reassess' alert on a bidirectional
        cross of the plan's static flip price.

        The detector never recomputes GEX (the stream carries no OI/greeks), so this
        reuses the prep-time flip number: a cross means the regime *may* be inverting,
        and the right action is for the human to re-run ``/scalp prep`` for a fresh
        map — not an automatic fade↔break switch. A ``flip_margin`` band debounces
        tick-noise right on the line; the first observation only records the side.
        """
        flip = plan.zero_gamma
        if flip is None:
            return
        prev = self._flip_side.get(symbol)
        if prev is None:
            self._flip_side[symbol] = "above" if price >= flip else "below"
            return
        if prev == "below" and price >= flip + self._flip_margin:
            self._flip_side[symbol] = "above"
            self._notify(_flip_message(symbol, price, flip, "up"))
        elif prev == "above" and price <= flip - self._flip_margin:
            self._flip_side[symbol] = "below"
            self._notify(_flip_message(symbol, price, flip, "down"))

    def _in_zone(self, level: Level, price: float, confirming: str) -> bool:
        """Geometry gate: fade = within tolerance; break = crossed by break_margin."""
        if level.mode == "break":
            if confirming == "buy":
                return price >= level.price + self._break_margin
            return price <= level.price - self._break_margin
        return abs(price - level.price) <= self._tolerance

    def _cleared(self, level: Level, price: float, confirming: str) -> bool:
        """Re-arm gate: fade = left the band; break = retraced back across the level."""
        if level.mode == "break":
            return price <= level.price if confirming == "buy" else price >= level.price
        return abs(price - level.price) > self._tolerance + self._rearm_margin

    def _fire(self, plan: SessionPlan, symbol: str, level: Level) -> None:
        """Prompt the human; propose the bracket if there's a contract with a tradeable spread."""
        message = self._message(symbol, level)
        if level.contract and self._propose is not None:
            if self._spread_ok(level.contract):
                self._notify(message)
                self._propose(
                    TradeProposal(
                        contract=level.contract,
                        quantity=plan.contracts,
                        stop_pct=plan.default_stop_pct,
                        target_pct=plan.target_pct,
                        reason=message,
                    )
                )
            else:
                self._notify(f"{message} — option spread too wide; alert only, no paper fill")
        else:
            self._notify(message)

    def _spread_ok(self, contract: str) -> bool:
        """Spread gate (proposal only): True unless the option's quoted spread is too wide."""
        q = self._quotes.get(contract)
        if q is None or q.bid is None or q.ask is None or q.ask <= 0:
            return True  # no quote to judge — best-effort, don't block
        return (q.ask - q.bid) / q.ask <= self._spread_max_pct

    def _message(self, symbol: str, level: Level) -> str:
        tape = _TAPE_PHRASE.get(self._tape_side.get(symbol, "mixed"), "tape mixed")
        verb = "broke" if level.mode == "break" else "tagged"
        return (
            f"{symbol} {verb} {level.price:g} {level.side} [{level.mode}] — "
            f"{tape}{self._book_note(symbol)}; plan stop {level.stop:g}"
        )

    def _book_note(self, symbol: str) -> str:
        """Soft top-of-book imbalance annotation (never a gate — inside-quote only)."""
        q = self._quotes.get(symbol)
        if q is None or q.bid_size is None or q.ask_size is None:
            return ""
        sizes = f" {q.bid_size}x{q.ask_size}"
        if q.bid_size > q.ask_size * 1.5:
            return f"; book bid-heavy{sizes}"
        if q.ask_size > q.bid_size * 1.5:
            return f"; book offer-heavy{sizes}"
        return f"; book balanced{sizes}"


def _flip_message(symbol: str, price: float, flip: float, direction: str) -> str:
    """Tripwire alert text. Down-cross = leaving the +GEX (pinning) zone into −GEX
    (trending) in the normal flip-below-spot case — the dangerous one (stop fading);
    up-cross = pinning may be reasserting. Either way: re-pull the gamma map."""
    if direction == "down":
        arrow, regime = "↓ below", "pinning may be giving way to trending — stop fading walls"
    else:
        arrow, regime = "↑ above", "pinning may be reasserting"
    return (
        f"⚠ {symbol} crossed the zero-gamma flip {flip:g} {arrow} ({price:g}) — "
        f"regime may be inverting; re-run /scalp prep for a fresh map ({regime})"
    )


def _tape_side(ts: TimeSale) -> str:
    if ts.ask is not None and ts.price >= ts.ask:
        return "buy"  # printing at/above the offer — buyers lifting
    if ts.bid is not None and ts.price <= ts.bid:
        return "sell"  # printing at/below the bid — sellers hitting
    return "mixed"


def _confirming_side(level: Level) -> str:
    """The tape aggressor side that confirms this level's trade direction (buy/sell)."""
    if level.contract is not None:
        try:
            _root, _exp, opt_type, _strike = parse_occ(level.contract)
            return "buy" if opt_type == "call" else "sell"
        except (IndexError, ValueError):
            pass  # malformed contract — fall back to side + mode
    # alert-only (or unparseable): derive direction from side + mode
    # (break inverts the fade mapping: a resistance breakout is a long, not a short)
    bullish = (level.side == "support") == (level.mode != "break")
    return "buy" if bullish else "sell"


def _lean_allows(lean: str, confirming: str) -> bool:
    """Gate on the trade *direction* (buy=long, sell=short), so break-mode flips work."""
    if lean == "both":
        return True
    if lean == "long-only":
        return confirming == "buy"
    if lean == "short-only":
        return confirming == "sell"
    return False  # no-trade / unknown


def watch_setups(feed: MarketDataFeed, detector: SetupDetector) -> None:
    """Wire the underlying tape + quotes into the detector (quotes, trades, timesales)."""
    feed.on_quote(detector.on_quote)
    feed.on_trade(detector.on_trade)
    feed.on_timesale(detector.on_timesale)
