"""SetupDetector — fires a confirmed entry when the underlying tags a blessed level.

On a *degraded* view (top-of-book + tape, no L2 ladder) it confirms a setup from
three things that are all already on the wire:

1. **Geometry** keyed to the level's ``mode``:
   - ``fade`` (positive-GEX setup): price touches within ``tolerance`` of the level
     — the mean-reversion trade at a gamma wall (touch-and-reject).
   - ``break`` (negative-GEX setup): price *crosses* the level by ``break_margin``
     in the trade's direction — the momentum trade (cross-and-follow-through).
2. **Lean** — the plan's ``lean`` must allow the trade *direction* (a long needs
   ``long-only`` or ``both``; a short needs ``short-only`` or ``both``).
3. **Tape** — the last timesale's aggressor side must agree with the trade
   direction (a long wants buyers lifting offers; a short wants sellers hitting
   bids). Direction is read from the level's ``direction`` (``long``/``short``);
   for an alert-only level (no ``direction``) it's derived from ``side`` + ``mode``.

Only a setup that clears all three fires — there is no bare-touch heads-up. The
fire ``notify``s the human and, if the level names a ``direction``, emits a
``TradeProposal`` so the paper broker auto-executes the same absolute-price bracket.
A **spread gate** sits on the proposal only: a confirmed-but-wide book still alerts
(work a limit) but is not paper-filled, keeping the paper book's fills honest. The
top-of-book size imbalance is a soft annotation, never a gate.

Hysteresis: ``_active`` is set only on a *confirmed* fire, so an unconfirmed tag
keeps re-evaluating in-zone until the tape turns, then fires once; it re-arms
when price leaves the zone. Tape direction comes from timesales, so a level seen
only by trades (no timesale) waits for a tape print before it can confirm.

Re-fire cooldown (``_on_cooldown``): hysteresis stops a *continuous* in-zone fire,
but a wall that oscillates out-and-back re-arms and would re-fire on every re-entry —
which during a regime mismatch machine-guns brackets (the 2026-06-18 740-fade bled
−$254 over 61 trips in the open hour). So each level carries a per-level cooldown:
after a fire it can't re-fire for ``cooldown_s`` (default 5 min, the value that turns
that day green). It's a rate limit, not a session cap — a real trend still fires
repeatedly, just spaced — and it's per ``Level`` so a wall's reversal/retest rows and
distinct levels cool independently. Like the gap guard, it's measured off the stream's
print ``ms`` and is a no-op on a ms-less feed.

**Break arming** (``_armed``): a break is a *one-time* edge event, but the
geometry gate (``_in_zone``) only asks "is price currently across the level?" —
true for the whole extended move after the cross. So a break level fires only
once the detector has *witnessed* price on the pre-break (setup) side — below a
resistance breakout, above a support breakdown. A cold start (or a re-arm) with
price already extended past the level stays un-armed and silent until price comes
back and crosses again. Fade levels need no arming — they re-test their level all
session, so they self-correct. **Gap re-arm** (``_check_gap``): a laptop *suspend*
freezes the process without killing it, so ``_armed`` survives the sleep and would
let the daemon fire at the extended top on wake. A long gap between print
timestamps (``gap_s``) means the stream was suspended/disconnected, so all arming
+ fired state is dropped: every break level must re-witness its setup side before
it can fire again. This is the guard that makes waking the machine safe.

Two further ``mode`` values render the verdict the bare ``break`` cannot — whether a
cross *holds* or *fails* — via a per-wall :class:`~trading_scalper.breakout.BreakoutTracker`
(see ``breakout.py`` for the state machine and the inside/outside conventions):

- ``reversal`` — fires when a cross-out **snaps back inside** without committing (a *failed*
  break); trades the snap-back, opposite the attempt.
- ``retest`` — fires when a break **confirms** (held / pushed through) and then **pulls back
  to the wall and resumes**; the patient continuation entry.

A wall is two ``Level`` rows at one price+side (a ``reversal`` row + a ``retest`` row, each
naming its own option); both feed one tracker and the rendered verdict fires the matching
row. Unlike ``fade``/``break``, these are gated on **geometry + lean only, never tape** — the
snap-back *timing* is the signal, and tape absorption was verified (n=61, 2026-06-18) not to
separate winners from losers on this feed. Tape stays the soft annotation in the message.
The tracker is level-*source*-agnostic (a gamma wall is just one source), and the stream-gap
guard drops its cross-timers on a suspend exactly as it drops ``break`` arming.

On every confirmed fire the detector also emits a ``FireRecord`` of **B4
velocity/absorption telemetry** (trailing-window underlying velocity, cumulative
confirming vs contrary tape size, top-of-book imbalance) through an optional
``record`` sink. This is *recorded, never gated* — the paper run needs the raw
numbers next to the eventual win/loss to learn which of them actually separate
winners from losers before any of them is allowed to veto a setup.

Separately, the **zero-gamma tripwire** (``_check_flip``) watches the underlying
cross the plan's static flip price in *either* direction and fires a non-trading
"the regime may be inverting — re-run /scalp prep" alert. It is not gated on
lean/tape/contract and proposes nothing; it never recomputes GEX (the stream has
no OI/greeks) — it reuses the prep-time number, so a cross means *reassess*, not
an automatic fade↔break switch.
"""

from collections import deque
from collections.abc import Callable
from typing import NamedTuple

from trading_clients.market_stream import Quote, TimeSale, Trade

from trading_scalper.breakout import BreakoutTracker, Verdict
from trading_scalper.domain import FireRecord, OrderId, Side, TradeProposal
from trading_scalper.plan import Level, SessionPlan
from trading_scalper.ports import MarketDataFeed

_TAPE_PHRASE = {"buy": "tape lifting offers", "sell": "tape hitting bids", "mixed": "tape mixed"}
_VERDICT_MODES = ("reversal", "retest")  # geometry-driven verdicts — handled by BreakoutTracker
_MOMENTUM_MODES = ("break", "retest")  # continuation modes; the rest mean-revert back inside
_VERB = {
    "break": "broke",
    "reversal": "failed-break reversal at",
    "retest": "breakout retest at",
}
type _WallKey = tuple[float, str]  # (price, side) — one breakout tracker per wall


class _Tick(NamedTuple):
    """One trailing-window tape print. ``side`` is the aggressor (timesale) or
    ``"unknown"`` for a bare trade that carries no bid/ask to classify it."""

    ms: int | None
    price: float
    size: int
    side: str  # "buy" | "sell" | "unknown"


class SetupDetector:
    def __init__(
        self,
        plan_source: Callable[[], SessionPlan | None],
        notify: Callable[[str], None],
        propose: Callable[[TradeProposal], OrderId | None] | None = None,
        *,
        # ── geometry, in index points — scaled ~10× from the QQQ-era defaults for the
        # /ES-family price magnitude (~6250 vs QQQ ~600); recalibrate against recorded
        # /MES tape as 6/23 did for QQQ (a fresh version cohort insulates the history).
        tolerance: float = 1.0,
        rearm_margin: float = 0.5,
        break_margin: float = 0.5,
        spread_max_pct: float = 0.10,
        flip_margin: float = 1.0,
        record: Callable[[FireRecord], None] | None = None,
        window_s: float = 5.0,
        window_max: int = 256,
        gap_s: float = 90.0,
        cooldown_s: float = 300.0,
        min_break_excursion: float = 7.5,
        follow_through_margin: float = 20.0,
        confirm_s: float = 150.0,
        failure_window_s: float = 120.0,
        reentry_margin: float = 1.0,
        retest_proximity: float = 2.0,
        retest_window_s: float = 360.0,
    ) -> None:
        self._plan_source = plan_source
        self._notify = notify
        self._propose = propose
        self._tolerance = tolerance
        self._rearm_margin = rearm_margin
        self._break_margin = break_margin
        self._spread_max_pct = spread_max_pct
        self._flip_margin = flip_margin
        self._record = record
        self._window_s = window_s
        self._window_max = window_max
        self._gap_ms = int(gap_s * 1000)  # inter-print gap that means the stream was suspended
        self._cooldown_ms = int(cooldown_s * 1000)  # min spacing between re-fires of one level
        # verdict-mode (reversal/retest) tunables — calibrated off the 6/18+6/22 QQQ 740 tape
        self._breakout_kw = {
            "break_margin": break_margin,
            "min_break_excursion": min_break_excursion,
            "follow_through_margin": follow_through_margin,
            "confirm_s": confirm_s,
            "failure_window_s": failure_window_s,
            "reentry_margin": reentry_margin,
            "retest_proximity": retest_proximity,
            "retest_window_s": retest_window_s,
        }
        self._tape_side: dict[str, str] = {}
        self._tape: dict[str, deque[_Tick]] = {}  # symbol -> trailing-window prints (B4 telemetry)
        self._quotes: dict[str, Quote] = {}  # symbol -> latest top-of-book (underlying + options)
        self._active: set[Level] = set()  # levels currently fired (re-arm on leaving the zone)
        self._armed: set[Level] = set()  # break levels that have witnessed their setup side
        self._trackers: dict[_WallKey, BreakoutTracker] = {}  # one verdict machine per wall
        self._last_fire_ms: dict[Level, int] = {}  # level -> last fire ts, for the re-fire cooldown
        self._last_ms: dict[str, int] = {}  # symbol -> last print ts, for stream-gap detection
        self._flip_side: dict[str, str] = {}  # symbol -> "above" | "below" the zero-gamma flip

    def on_quote(self, quote: Quote) -> None:
        self._quotes[quote.symbol] = quote

    def on_trade(self, trade: Trade) -> None:
        self._push_tape(trade.symbol, trade.price, trade.size, "unknown", trade.ms)
        self._evaluate(trade.symbol, trade.price, trade.ms)

    def on_timesale(self, ts: TimeSale) -> None:
        side = _tape_side(ts)
        self._tape_side[ts.symbol] = side
        self._push_tape(ts.symbol, ts.price, ts.size, side, ts.ms)
        self._evaluate(ts.symbol, ts.price, ts.ms)

    def _evaluate(self, symbol: str, price: float, ms: int | None = None) -> None:
        plan = self._plan_source()
        if plan is None or plan.symbol != symbol:
            return
        self._check_gap(symbol, ms)  # a long gap -> distrust arming, force a re-witness
        self._check_flip(plan, symbol, price)
        self._eval_breakouts(plan, symbol, price, ms)  # reversal/retest verdicts (no tape gate)
        tape = self._tape_side.get(symbol, "mixed")
        for level in plan.levels:
            if level.mode in _VERDICT_MODES:
                continue  # handled by the BreakoutTracker path — not tape-gated
            key = level  # the whole level: two levels at one price+side (diff mode/contract) co-arm
            confirming = _confirming_side(level)
            if self._on_setup_side(level, price, confirming):
                self._armed.add(key)  # witnessed the setup side -> eligible to fire on the cross
            if self._in_zone(level, price, confirming):
                if (
                    key not in self._active
                    and (level.mode != "break" or key in self._armed)
                    and _lean_allows(plan.lean, confirming)
                    and tape == confirming
                    and not self._on_cooldown(key, ms)
                ):
                    self._active.add(key)
                    self._fire(plan, symbol, level, price, confirming, ms)
            elif key in self._active and self._cleared(level, price, confirming):
                self._active.discard(key)  # left the zone -> re-arm this level

    def _eval_breakouts(self, plan: SessionPlan, symbol: str, price: float, ms: int | None) -> None:
        """Drive the verdict state machines (one per wall) and fire on a resolution.

        A wall is expressed as up to two ``Level`` rows at one price+side: a ``reversal``
        row (the failed-break snap-back contract) and a ``retest`` row (the confirmed-break
        continuation contract). Both feed one :class:`BreakoutTracker`; whichever verdict
        the tracker renders fires the matching row. Gated on geometry + lean only — **not
        tape** (the snap-back timing is the signal; tape is the soft annotation in the
        message). Trackers for walls no longer in the plan are pruned (hot-reload safe)."""
        walls = self._breakout_walls(plan)
        for stale in [k for k in self._trackers if k not in walls]:
            del self._trackers[stale]
        for wall_key, rows in walls.items():
            tracker = self._trackers.get(wall_key)
            if tracker is None:
                tracker = self._trackers[wall_key] = BreakoutTracker(
                    price=wall_key[0], side=wall_key[1], **self._breakout_kw
                )
            verdict = tracker.update(price, ms)
            if verdict is None:
                continue
            level = rows.get("reversal" if verdict is Verdict.REVERSAL else "retest")
            if level is None:
                continue  # no contract row for this verdict on this wall — nothing to fire
            confirming = _confirming_side(level)
            if _lean_allows(plan.lean, confirming) and not self._on_cooldown(level, ms):
                self._fire(plan, symbol, level, price, confirming, ms)

    @staticmethod
    def _breakout_walls(plan: SessionPlan) -> dict[_WallKey, dict[str, Level]]:
        """Group ``reversal``/``retest`` levels by their wall (price, side) → {mode: level}."""
        walls: dict[_WallKey, dict[str, Level]] = {}
        for level in plan.levels:
            if level.mode in _VERDICT_MODES:
                walls.setdefault((round(level.price, 4), level.side), {})[level.mode] = level
        return walls

    def _check_gap(self, symbol: str, ms: int | None) -> None:
        """A long gap between consecutive prints = the stream froze (laptop suspend /
        socket drop). The in-memory ``_armed`` / ``_active`` / tracker state survived the
        freeze but no longer reflects reality, so drop it: every break and verdict level
        must re-witness its setup side before it can fire again. Without this, a daemon
        that slept through the actual cross wakes already-armed-and-extended and fires at
        the top (and a verdict tracker's cross-timer would span the dead time)."""
        if ms is None:
            return
        last = self._last_ms.get(symbol)
        self._last_ms[symbol] = ms
        live = self._armed or self._active or self._trackers
        if last is not None and ms - last > self._gap_ms and live:
            self._armed.clear()
            self._active.clear()
            self._trackers.clear()  # cross-timers spanning the gap are invalid — rebuild fresh
            self._last_fire_ms.clear()  # post-gap fires are fresh setups — drop stale cooldowns
            self._notify(_gap_message(symbol, (ms - last) / 1000.0))

    def _on_cooldown(self, level: Level, ms: int | None) -> bool:
        """True when this level fired within ``cooldown_s`` — caps the re-fire *rate*.

        A wall oscillating in and out of its zone re-arms and would re-fire on every
        re-entry; during a regime mismatch that machine-guns brackets (the 2026-06-18
        740-fade bled −$254 over 61 trips in the open hour — a 5-min cooldown turns the
        day green). Keyed per ``Level`` (price+side+mode+contract), so a wall's reversal
        and retest rows cool independently and a genuine *new* setup at a different level
        is never blocked; it only damps the *same* setup re-firing too fast. This is a
        rate limit, not a session cap — a long trend still fires repeatedly, just spaced
        (a max-fires-per-session cap would instead choke the good trend days, so it's
        deliberately not that).

        Time-based off the stream's print ``ms``; a ms-less feed (sandbox / bare trades)
        has no time base, so the cooldown degrades to a no-op there — same contract as
        the gap guard and the verdict timers.
        """
        if ms is None or self._cooldown_ms <= 0:
            return False
        last = self._last_fire_ms.get(level)
        return last is not None and ms - last < self._cooldown_ms

    def _on_setup_side(self, level: Level, price: float, confirming: str) -> bool:
        """True when price sits on the pre-break (setup) side of a *break* level —
        at/below a resistance breakout, at/above a support breakdown. Observing this
        arms the level. Fade levels need no arming (they re-test their level all day)."""
        if level.mode != "break":
            return False
        return price <= level.price if confirming == "buy" else price >= level.price

    def _push_tape(
        self, symbol: str, price: float, size: int | None, side: str, ms: int | None
    ) -> None:
        """Append a print to the symbol's trailing window, then prune by age.

        Length is hard-capped (``window_max``) so a ms-less feed can't grow it
        unbounded; when prints carry timestamps it's additionally trimmed to the
        last ``window_s`` seconds, the window the velocity/absorption read uses.
        """
        dq = self._tape.get(symbol)
        if dq is None:
            dq = self._tape[symbol] = deque(maxlen=self._window_max)
        dq.append(_Tick(ms, price, size or 0, side))
        if ms is not None:
            cutoff = ms - int(self._window_s * 1000)
            # drop aged prints AND any leading timestamp-less one, so a single ms=None
            # head (a bare trade) can't pin the window and keep stale prints alive
            while dq and (dq[0].ms is None or dq[0].ms < cutoff):
                dq.popleft()

    def _tape_metrics(self, symbol: str, confirming: str) -> tuple[float | None, int, int]:
        """(velocity $/s, cumulative confirming-side size, cumulative contrary-side
        size) over the trailing window — the B4 telemetry, computed only at fire time."""
        dq = self._tape.get(symbol)
        if not dq:
            return None, 0, 0
        contrary = "sell" if confirming == "buy" else "buy"
        cum_conf = sum(t.size for t in dq if t.side == confirming)
        cum_contra = sum(t.size for t in dq if t.side == contrary)
        return _velocity(dq), cum_conf, cum_contra

    def _book_imbalance(self, symbol: str) -> int | None:
        """Underlying top-of-book ``bid_size - ask_size`` at the fire (None if unquoted)."""
        q = self._quotes.get(symbol)
        if q is None or q.bid_size is None or q.ask_size is None:
            return None
        return q.bid_size - q.ask_size

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

    def _fire(
        self,
        plan: SessionPlan,
        symbol: str,
        level: Level,
        price: float,
        confirming: str,
        ms: int | None,
    ) -> None:
        """Prompt the human; propose the bracket if there's a contract with a tradeable spread.

        Prompts and proposes first so the bracket's ``bracket_id`` (the placed
        entry-order id, or ``None`` for an alert-only / spread-suppressed fire) can
        be stamped on the ``FireRecord``. The record is then emitted on *every*
        fire — alert-only and spread-suppressed setups included — so the telemetry
        log holds one row per confirmed setup, joinable to the bracket's fills.

        Stamps the level's cooldown clock from the fire's print ``ms`` so the next
        re-fire of this same level is rate-limited; a ms-less fire leaves the clock
        unset (no time base), degrading the cooldown to a no-op as elsewhere.
        """
        if ms is not None:
            self._last_fire_ms[level] = ms
        message = self._message(symbol, level)
        bracket_id = self._prompt(plan, symbol, level, confirming, message)
        if self._record is not None:
            velocity, cum_conf, cum_contra = self._tape_metrics(symbol, confirming)
            self._record(
                FireRecord(
                    symbol=symbol,
                    level=level.price,
                    side=level.side,
                    mode=level.mode,
                    confirming=confirming,
                    price=price,
                    # the traded instrument for a tradeable level, else None (alert-only)
                    contract=(symbol if level.direction is not None else None),
                    bracket_id=bracket_id,
                    velocity=velocity,
                    cum_confirming_size=cum_conf,
                    cum_contrary_size=cum_contra,
                    book_imbalance=self._book_imbalance(symbol),
                )
            )

    def _prompt(
        self, plan: SessionPlan, symbol: str, level: Level, confirming: str, message: str
    ) -> OrderId | None:
        """Notify the human and, on a tradeable level with a sane bracket + tight spread,
        place the paper bracket; return its ``bracket_id`` (entry-order id) or ``None``.

        A level with no ``direction`` is alert-only. An inverted bracket (stop/target on
        the wrong side of the level for the direction) or a too-wide book alerts but is
        not paper-filled, keeping the paper book's fills honest.
        """
        if level.direction is None or self._propose is None:
            self._notify(message)
            return None
        direction = Side.BUY if confirming == "buy" else Side.SELL
        stop_price, target_price = self._bracket_prices(plan, level, confirming)
        if not _bracket_sane(confirming, level.price, stop_price, target_price):
            self._notify(
                f"{message} — bracket geometry inverted "
                f"(stop {stop_price:g} / target {target_price:g}); alert only, no paper fill"
            )
            return None
        if not self._spread_ok(symbol):
            self._notify(f"{message} — spread too wide; alert only, no paper fill")
            return None
        self._notify(message)
        return self._propose(
            TradeProposal(
                symbol=symbol,
                direction=direction,
                quantity=plan.contracts,
                stop_price=stop_price,
                target_price=target_price,
                reason=message,
            )
        )

    def _bracket_prices(
        self, plan: SessionPlan, level: Level, confirming: str
    ) -> tuple[float, float]:
        """Resolve the bracket's absolute stop/target prices for a fire.

        Explicit ``level.stop`` / ``level.target`` win; otherwise each is derived by
        offsetting the level price by the plan's default points on the correct side for
        the trade direction (``confirming`` = buy → long: stop below, target above; a
        short is the mirror)."""
        if confirming == "buy":  # long
            stop = level.stop if level.stop is not None else level.price - plan.default_stop_points
            target = (
                level.target
                if level.target is not None
                else level.price + plan.default_target_points
            )
        else:  # short
            stop = level.stop if level.stop is not None else level.price + plan.default_stop_points
            target = (
                level.target
                if level.target is not None
                else level.price - plan.default_target_points
            )
        return stop, target

    def _spread_ok(self, contract: str) -> bool:
        """Spread gate (proposal only): True unless the option's quoted spread is too wide."""
        q = self._quotes.get(contract)
        if q is None or q.bid is None or q.ask is None or q.ask <= 0:
            return True  # no quote to judge — best-effort, don't block
        if q.bid > q.ask:
            return False  # crossed/locked book — un-modelable, don't paper-fill
        return (q.ask - q.bid) / q.ask <= self._spread_max_pct

    def _message(self, symbol: str, level: Level) -> str:
        tape = _TAPE_PHRASE.get(self._tape_side.get(symbol, "mixed"), "tape mixed")
        verb = _VERB.get(level.mode, "tagged")
        stop_txt = f"; plan stop {level.stop:g}" if level.stop is not None else ""
        return (
            f"{symbol} {verb} {level.price:g} {level.side} [{level.mode}] — "
            f"{tape}{self._book_note(symbol)}{stop_txt}"
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


def _gap_message(symbol: str, gap_s: float) -> str:
    """Operational notice on a detected stream discontinuity (suspend/disconnect)."""
    return (
        f"⚠ {symbol} stream gap {gap_s:.0f}s (suspend/disconnect?) — re-arming: break and "
        f"reversal/retest levels need a fresh setup-side touch before they can fire again"
    )


def _velocity(dq: deque[_Tick]) -> float | None:
    """Signed underlying $/s across the window's first→last *timestamped* prints.

    ``None`` when fewer than two prints carry a timestamp (e.g. a sandbox feed) or
    they share one — there's no time base to divide by. Sign follows price: negative
    = falling into the level, positive = rising into it.
    """
    stamped = [(t.ms, t.price) for t in dq if t.ms is not None]
    if len(stamped) < 2:
        return None
    (ms0, p0), (ms1, p1) = stamped[0], stamped[-1]
    dt = (ms1 - ms0) / 1000.0
    if dt <= 0:
        return None
    return (p1 - p0) / dt


def _tape_side(ts: TimeSale) -> str:
    if ts.ask is not None and ts.price >= ts.ask:
        return "buy"  # printing at/above the offer — buyers lifting
    if ts.bid is not None and ts.price <= ts.bid:
        return "sell"  # printing at/below the bid — sellers hitting
    return "mixed"


def _confirming_side(level: Level) -> str:
    """The tape aggressor side that confirms this level's trade direction (buy/sell)."""
    if level.direction == "long":
        return "buy"
    if level.direction == "short":
        return "sell"
    # alert-only (direction None) or unrecognized: derive direction from side + mode.
    # momentum modes (break, retest) go *with* the cross — a resistance breakout/retest is
    # a long; mean-revert modes (fade, reversal) go back *inside* — a failed-break reversal
    # at resistance is a short, mirroring fade.
    bullish = (level.side == "support") != (level.mode in _MOMENTUM_MODES)
    return "buy" if bullish else "sell"


def _bracket_sane(confirming: str, anchor: float, stop: float, target: float) -> bool:
    """Guard against an inverted bracket: a long needs ``stop < anchor < target``; a
    short the mirror (``target < anchor < stop``). ``anchor`` is the level price (the
    entry proxy — fills land within a margin of it)."""
    if confirming == "buy":
        return stop < anchor < target
    return target < anchor < stop


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
