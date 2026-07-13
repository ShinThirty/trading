"""Instrument profiles: the per-root facts the **exchange has no opinion about**.

This registry deliberately holds *only* what tastytrade can't tell us, because
anything it can tell us it should:

- ``geometry`` — the detector's price-distance bands (see :class:`Geometry`). These
  scale with the index's *price magnitude / volatility* (the S&P complex ~7600 vs
  the Nasdaq complex ~29800), so a wall-tolerance sized for /MES is simply wrong on
  /MNQ. Threading it from here (not defaulting silently in the detector) keeps that
  coupling explicit: pick a symbol, get its bands. This is **our calibration**, not
  an instrument fact — no API has a view on it.
- ``reference`` — the **cash-index** streamer symbol whose gamma walls drive the
  level map and against which the carry basis is measured (``SPX`` for the S&P
  complex, ``NDX`` for Nasdaq). Instrument-correlated — /MES tracks the S&P, /MNQ
  the Nasdaq — but it's **our level-source decision**, so it lives here rather than
  being hardcoded to SPX in the CLI or the skill.

What is *not* here, on purpose:

- **$/point and tick.** The exchange states them (``notional-multiplier`` /
  ``tick-size``); ``contract.py`` reads them off the resolved contract and hands them
  to the ``PaperBroker``. A second copy typed in here could only ever *disagree* with
  the venue we clear against — and a paper session that prices P&L off the wrong
  multiplier looks completely normal while being completely wrong.
- **Which month is live.** Also the exchange's (``active-month``). This registry used
  to compute it from quarterly codes and an 8-day roll heuristic; that guess is gone,
  because a wrong front month fails silently — it still streams, still fires, still
  fills, on a dying book.

A dated contract from the feed (e.g. ``/MESU26:XCME``) resolves to its root's profile
by prefix, so the plan can name either the continuous root or a specific month.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Geometry:
    """The detector's price-distance bands (index points) for one instrument.

    These are exactly the tunables that **scale with the instrument's price
    magnitude / volatility** — the reason the same ``SetupDetector`` can't share
    one band-set across the S&P and Nasdaq complexes. The *time* windows (seconds)
    and structural gates (spread %, buffer cap) do **not** scale with the
    instrument and deliberately stay on the detector, not here.

    Defaults are the S&P set (``/MES`` / ``/ES``); a partial ``Geometry(break_margin
    =0.5)`` keeps every other band at that default. Per-field origin/derivation notes
    live in ``detector.py`` and ``breakout.py`` — this is the knob table, not the
    rationale.
    """

    tolerance: float = 1.0  # fade: within this of the level == a tag
    rearm_margin: float = 0.5  # extra distance out of the fade band before a level re-arms
    break_margin: float = 0.5  # distance past a level that counts as a break/cross
    flip_margin: float = 1.0  # zero-gamma tripwire debounce band
    min_break_excursion: float = 7.5  # commit distance a break must clear to be tradeable
    follow_through_margin: float = 20.0  # excursion that confirms a break by distance alone
    reentry_margin: float = 1.0  # distance back inside that counts as a genuine re-cross
    retest_proximity: float = 2.0  # distance from the wall that counts as a retest touch


# S&P complex (index ~7600): the reference set. Origin is the QQQ 740 tape scaled
# ~10× at the futures migration — an honest first cut, pending recalibration against
# recorded /MES tape (see detector.py / breakout.py per-field notes).
_SP500_GEOMETRY = Geometry()

# Nasdaq complex (index ~29800 ≈ 3.9× the S&P): the S&P bands scaled ~4× by price
# ratio. UNCALIBRATED — never validated against recorded /MNQ tape; runnable for
# paper, but its numbers are a placeholder, not an edge. Same status the S&P set had
# at the migration, one magnitude over. Recalibrate before trusting a /MNQ cohort.
_NASDAQ_GEOMETRY = Geometry(
    tolerance=4.0,
    rearm_margin=2.0,
    break_margin=2.0,
    flip_margin=4.0,
    min_break_excursion=30.0,
    follow_through_margin=80.0,
    reentry_margin=4.0,
    retest_proximity=8.0,
)


@dataclass(frozen=True, slots=True)
class Profile:
    """What we bring to a futures root; the exchange brings the economics."""

    root: str
    geometry: Geometry  # the detector's price-distance bands for this index's magnitude
    reference: str  # cash-index streamer symbol for gamma walls + carry basis (SPX / NDX)


# Insertion order matters for prefix resolution: longer roots (/MES, /MNQ) come
# before the shorter ones (/ES, /NQ) they'd otherwise shadow. Geometry AND reference
# pair by index (S&P vs Nasdaq), not by micro-vs-full — /MES and /ES share one price
# map and one cash index (SPX); /MNQ and /NQ share the Nasdaq's (NDX). Adding a root
# means answering only these two questions; its $/pt and tick arrive from the API.
_PROFILES: dict[str, Profile] = {
    "/MES": Profile("/MES", _SP500_GEOMETRY, "SPX"),  # Micro E-mini S&P 500
    "/MNQ": Profile("/MNQ", _NASDAQ_GEOMETRY, "NDX"),  # Micro E-mini Nasdaq-100
    "/ES": Profile("/ES", _SP500_GEOMETRY, "SPX"),  # E-mini S&P 500
    "/NQ": Profile("/NQ", _NASDAQ_GEOMETRY, "NDX"),  # E-mini Nasdaq-100
}


def profile_for(symbol: str) -> Profile:
    """The geometry + cash-index reference for a symbol, resolving a dated contract by prefix.

    Raises ``KeyError`` for an unknown root rather than silently handing back the S&P
    bands — a typo in the plan should fail loudly, not scalp /MNQ with /MES tolerances.
    """
    profile = _PROFILES.get(symbol)
    if profile is not None:
        return profile
    for root, base in _PROFILES.items():
        if symbol.startswith(root):
            return base
    raise KeyError(f"unknown futures symbol {symbol!r}; known roots: {', '.join(_PROFILES)}")


def root_of(symbol: str) -> str:
    """The instrument root a (possibly dated) streamer symbol belongs to.

    ``/MESU26:XCME`` → ``/MES``; ``/MES`` → ``/MES``. Falls back to the raw symbol for
    anything not in the registry (e.g. the pre-futures QQQ/SPY cohorts), so the scorecard
    can still bucket those by their own name. This is the cohort **grain**: grouping the
    track record by root — not the dated contract — is what keeps a quarterly roll (a new
    streamer symbol for the *same* instrument and behavior) from spuriously resetting a
    cohort. Same insertion-order-longest-first resolution as ``profile_for``.
    """
    for r in _PROFILES:
        if symbol.startswith(r):
            return r
    return symbol
