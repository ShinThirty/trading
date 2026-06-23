"""Breakout-attempt verdict state machine — false-break reversal + confirmed-break retest.

A gamma wall has exactly **three** physical resolutions, always: *touch-and-reject*,
*cross-and-fail*, and *cross-and-hold*. The legacy ``fade`` mode trades the first and
the legacy ``break`` mode fires synchronously on the cross (rendering no verdict on
whether it holds). This module renders the verdict the bare ``break`` could not:

- **REVERSAL** — price crossed *out* of the setup zone but **snapped back inside**
  within ``failure_window_s`` without ever committing (never reached
  ``follow_through_margin``). The break *failed*; trade the snap-back (opposite the
  attempted direction). This was the trade of the day on both 2026-06-18 and 2026-06-22,
  unreachable by ``fade`` (which shorts the touch and gets run over) or ``break`` (which
  chases the poke and round-trips).
- **GO_WITH** — the break *confirmed* (held outside ``confirm_s`` or pushed past
  ``follow_through_margin``), then **pulled back to the wall and resumed**. The patient
  continuation entry — strictly later than the bare ``break``'s cross-fire.

The two are mutually exclusive on one attempt; the tracker resolves to one and disarms.

**Source-agnostic by construction.** A tracker is built from a *price* and which *side*
is "inside" (the pre-break setup side) — nothing about gamma. A gamma wall is just one
*level source*; an opening-range edge, a VWAP line, or a stop-cluster level plug into the
same machine unchanged (only the level source and the regime's role-mapping differ). Keep
it this way: do not let gamma-specific knowledge leak in here.

Geometry is the signal, **not tape** — the snap-back *timing* is what separates a failed
break from a hold, and tape absorption was verified (2026-06-18, n=61) not to separate
winners from losers on this feed (the real tell, L2 depth, isn't on the wire). Tape stays
a soft annotation at the detector layer; it never gates a verdict here.

``side`` semantics — "inside" is the pre-break side, "outside" the post-break side:

- **resistance**: inside = below the wall, outside = above. A confirmed break runs *up*
  (GO_WITH = long); a failed break snaps back *down* (REVERSAL = short).
- **support**: the exact mirror. Inside = above, outside = below. Confirmed break runs
  *down* (GO_WITH = short); failed break snaps back *up* (REVERSAL = long).

The tunables were **calibrated 2026-06-23** against the recorded 2026-06-18 (a chop/pin day)
and 2026-06-22 (a 740 downside breakdown) QQQ tape — see each field's comment for what the
data pinned. Two honest caveats from that calibration: (1) the headline win, 6/22's "trade of
the day," turned out to be a confirmed *breakdown + retest* (a GO_WITH), **not** a fast
false-break reversal as first framed — so the GO_WITH path is well-fit but the REVERSAL path's
``failure_window_s`` is only *negatively* bounded (no real fast-fail example in-window);
(2) ``min_break_excursion`` is the floor that stops the reversal path from machine-gunning
chop, set just above 6/18's observed 0.62 ceiling rather than from a positive example. Verdict
modes are for −GEX/trend or conflicted walls, **not** clean pins — pair with regime gating and
the per-level re-fire cooldown (backlog #3).
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Phase(StrEnum):
    """Where one breakout attempt sits in its lifecycle (one wall = one tracker)."""

    WATCHING = "watching"  # cold start / post-gap: must witness the inside (setup) side first
    INSIDE = "inside"  # witnessed inside; waiting for a cross-out to start an attempt
    CROSSED = "crossed"  # crossed out — racing snap-back (reversal) vs hold (confirm)
    CONFIRMED = "confirmed"  # break confirmed; waiting for a pullback-and-resume (retest)
    DONE = "done"  # a verdict fired or the attempt died; re-arms when price returns inside


class Verdict(StrEnum):
    REVERSAL = "reversal"  # failed break — fire the snap-back (opposite the attempt)
    GO_WITH = "go_with"  # confirmed break + retest hold — fire the continuation


@dataclass(slots=True)
class BreakoutTracker:
    """A single wall's breakout-attempt state machine. Feed it every ``(price, ms)`` tick
    via :meth:`update`; it returns a :class:`Verdict` on the tick a resolution fires, else
    ``None``. Timestamps drive the windows; ``ms=None`` ticks still advance geometry
    (cross / snap-back / follow-through) but skip the time-gated transitions, so a feed
    without timestamps degrades to geometry-only rather than stalling."""

    price: float
    side: str  # "resistance" | "support"
    # distance past the wall that starts an attempt (shared with the detector's break mode)
    break_margin: float = 0.05
    # ── tunables calibrated against the 2026-06-18 (chop) + 06-22 (breakdown) QQQ 740 tape ──
    # A break must commit this far past the wall to be tradeable in EITHER direction — gates both
    # the reversal qualification and the time-confirm. Set just above 6/18's 0.62 chop ceiling so
    # micro-pokes don't read as "failed breaks"; this single knob zeroes out the chop machine-gun.
    # The reversal path has no *positive* (real fast false-break) example in the 6/18+6/22 window,
    # so this floor is its main guard — revisit it on a day that actually shows one.
    min_break_excursion: float = 0.75
    # Excursion that confirms a break by distance alone (6/18 chop maxed at 0.62 so distance never
    # false-confirms; 6/22's breakdown reached ~2.0 by ~10:33).
    follow_through_margin: float = 2.00
    # Time held outside that confirms a break — kept ≥ failure_window_s so a still-reversible break
    # isn't prematurely time-confirmed; 6/22's breakdown still confirms before its ~5-min retest.
    confirm_s: float = 150.0
    # A snap-back within this of the cross = a failed break. Only negatively bounded here (6/22's
    # 60-min top must NOT read as a reversal); no fast-fail example in-window to positively fit it.
    failure_window_s: float = 120.0
    # Distance back inside that counts as a genuine re-cross (filters 6/18 sub-0.10 chop wiggles;
    # 6/22's retest peaked 0.08 below 740 so it never false-tripped the late-failure exit).
    reentry_margin: float = 0.10
    # Distance from the wall that counts as a retest touch (caught 6/22's bounce to 739.92).
    retest_proximity: float = 0.20
    # Retest-and-resume must complete within this of confirm. THE calibration fix: 6/22's
    # confirm→resume took ~4.5 min, so the old 120s placeholder would have missed the trade.
    retest_window_s: float = 360.0
    # ── internal state ──
    phase: Phase = field(default=Phase.WATCHING, init=False)
    _t0: int | None = field(default=None, init=False)  # cross timestamp
    _max_ex: float = field(default=0.0, init=False)  # peak outside excursion this attempt
    _confirm_ms: int | None = field(default=None, init=False)
    _retested: bool = field(default=False, init=False)

    def _excursion(self, price: float) -> float:
        """Signed distance past the wall: ``+`` outside (post-break), ``−`` inside (setup)."""
        out_sign = 1.0 if self.side == "resistance" else -1.0
        return (price - self.price) * out_sign

    def update(self, price: float, ms: int | None) -> Verdict | None:
        ex = self._excursion(price)
        phase = self.phase

        if phase is Phase.WATCHING:
            if ex <= 0:  # witnessed the inside (setup) side — now eligible to track an attempt
                self.phase = Phase.INSIDE
            return None

        if phase is Phase.INSIDE:
            if ex >= self.break_margin:
                self.phase = Phase.CROSSED
                self._t0 = ms
                self._max_ex = ex
                if self._max_ex >= self.follow_through_margin:  # one-tick gap straight to confirm
                    self._enter_confirmed(ms)
            return None

        if phase is Phase.CROSSED:
            self._max_ex = max(self._max_ex, ex)
            if self._max_ex >= self.follow_through_margin:  # confirm by distance (geometry-only)
                self._enter_confirmed(ms)
                return None
            if ex <= -self.reentry_margin:  # snapped back inside
                elapsed = _elapsed(ms, self._t0)
                committed = self._max_ex >= self.min_break_excursion
                fast = elapsed is None or elapsed <= self.failure_window_s
                if committed and fast:  # broke for real, then failed fast → tradeable reversal
                    self.phase = Phase.DONE
                    return Verdict.REVERSAL
                self.phase = Phase.INSIDE  # never committed, or too slow — not a reversal; re-track
                return None
            elapsed = _elapsed(ms, self._t0)  # confirm by time held outside (the primary confirm)
            if (
                elapsed is not None
                and elapsed >= self.confirm_s
                and ex > 0
                and self._max_ex
                >= self.min_break_excursion  # a hover that never committed ≠ a break
            ):
                self._enter_confirmed(ms)
            return None

        if phase is Phase.CONFIRMED:
            if ex <= -self.reentry_margin:  # late full failure — no go-with, too late to reverse
                self.phase = Phase.DONE
                return None
            elapsed = _elapsed(ms, self._confirm_ms)
            if elapsed is not None and elapsed > self.retest_window_s:
                self.phase = Phase.DONE  # missed the retest window — don't chase
                return None
            if not self._retested:
                if -self.reentry_margin < ex <= self.retest_proximity:  # pulled back to the wall
                    self._retested = True
            elif ex >= self.break_margin:  # resumed outward after the retest hold — go with it
                self.phase = Phase.DONE
                return Verdict.GO_WITH
            return None

        if phase is Phase.DONE:
            if ex <= -self.reentry_margin:  # well back inside — re-arm for a fresh attempt
                self._reset_inside()
            return None

        return None

    def _enter_confirmed(self, ms: int | None) -> None:
        self.phase = Phase.CONFIRMED
        self._confirm_ms = ms
        self._retested = False

    def _reset_inside(self) -> None:
        self.phase = Phase.INSIDE
        self._t0 = None
        self._max_ex = 0.0
        self._confirm_ms = None
        self._retested = False


def _elapsed(ms: int | None, since: int | None) -> float | None:
    """Seconds between two epoch-ms stamps, or ``None`` if either is missing."""
    if ms is None or since is None:
        return None
    return (ms - since) / 1000.0
