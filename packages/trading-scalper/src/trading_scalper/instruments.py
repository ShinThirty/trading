"""Instrument registry: the per-symbol constants everything downstream keys off.

Each futures symbol carries three things that **change when you change the traded
instrument**, so they live together here as the single source of truth:

- ``point_value`` — $/point, the ``PaperBroker`` / ``Ledger`` multiplier.
- ``tick`` — the bracket-rounding grid.
- ``geometry`` — the detector's price-distance bands (see :class:`Geometry`). These
  scale with the index's *price magnitude / volatility* (the S&P complex ~7600 vs
  the Nasdaq complex ~29800), so a wall-tolerance sized for /MES is simply wrong on
  /MNQ. Threading it from here (not defaulting silently in the detector) keeps that
  coupling explicit: pick a symbol, get its bands.
- ``reference`` — the **cash-index** streamer symbol whose gamma walls drive the
  level map and against which the carry basis is measured (``SPX`` for the S&P
  complex, ``NDX`` for Nasdaq). Also instrument-correlated — /MES tracks the S&P,
  /MNQ the Nasdaq — so it lives here, not hardcoded to SPX in the CLI or the skill.

The CLI looks all four up for the traded symbol and hands them to the broker
(``point_value``/``tick``), the detector (``geometry``), and the carry-basis shadow
(``reference``). ``/MES`` is the default paper unit ($5/pt); ``/ES`` is the same
contract at 10× ($50/pt).

A specific contract month from the data feed (e.g. ``/MESU25:XCME``) resolves to
its root's economics — geometry and reference included — by prefix, so the plan can
name either the continuous root or a dated contract.
"""

from dataclasses import dataclass
from datetime import date, timedelta

# CME equity-index futures are quarterly: the front contract is Mar/Jun/Sep/Dec,
# expiring the third Friday of the contract month (settling to the S&P SOQ).
_QUARTERLY_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}

# Liquidity migrates to the next quarter ~8 calendar days before expiry (the CME
# roll date for the equity-index complex), so we roll the streamer symbol then —
# staying on the expiring contract past this means scalping a drying-up book.
_ROLL_DAYS = 8


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
class Instrument:
    symbol: str
    point_value: int  # dollars per 1.0 index point per contract (the ledger multiplier)
    tick: float  # minimum price increment
    geometry: Geometry  # the detector's price-distance bands for this instrument's magnitude
    reference: str  # cash-index streamer symbol for gamma walls + carry basis (SPX / NDX)


# Insertion order matters for prefix resolution: longer roots (/MES, /MNQ) come
# before the shorter ones (/ES, /NQ) they'd otherwise shadow. Geometry AND reference
# pair by index (S&P vs Nasdaq), not by micro-vs-full — /MES and /ES share one price
# map and one cash index (SPX); /MNQ and /NQ share the Nasdaq's (NDX).
_INSTRUMENTS: dict[str, Instrument] = {
    "/MES": Instrument("/MES", 5, 0.25, _SP500_GEOMETRY, "SPX"),  # Micro E-mini S&P 500
    "/MNQ": Instrument("/MNQ", 2, 0.25, _NASDAQ_GEOMETRY, "NDX"),  # Micro E-mini Nasdaq-100
    "/ES": Instrument("/ES", 50, 0.25, _SP500_GEOMETRY, "SPX"),  # E-mini S&P 500
    "/NQ": Instrument("/NQ", 20, 0.25, _NASDAQ_GEOMETRY, "NDX"),  # E-mini Nasdaq-100
}


def instrument_for(symbol: str) -> Instrument:
    """Look up a symbol's economics, resolving a dated contract to its root by prefix.

    Raises ``KeyError`` for an unknown symbol rather than silently guessing a
    multiplier — a typo in the plan should fail loudly, not paper-trade at $1/pt.
    """
    inst = _INSTRUMENTS.get(symbol)
    if inst is not None:
        return inst
    for root, base in _INSTRUMENTS.items():
        if symbol.startswith(root):
            return Instrument(symbol, base.point_value, base.tick, base.geometry, base.reference)
    raise KeyError(f"unknown futures symbol {symbol!r}; known roots: {', '.join(_INSTRUMENTS)}")


def root_of(symbol: str) -> str:
    """The instrument root a (possibly dated) streamer symbol belongs to.

    ``/MESU26:XCME`` → ``/MES``; ``/MES`` → ``/MES``. Falls back to the raw symbol for
    anything not in the registry (e.g. the pre-futures QQQ/SPY cohorts), so the scorecard
    can still bucket those by their own name. This is the cohort **grain**: grouping the
    track record by root — not the dated contract — is what keeps a quarterly roll (a new
    streamer symbol for the *same* instrument and behavior) from spuriously resetting a
    cohort. Same insertion-order-longest-first resolution as ``instrument_for``.
    """
    for r in _INSTRUMENTS:
        if symbol.startswith(r):
            return r
    return symbol


def third_friday(year: int, month: int) -> date:
    """The third Friday of a month — CME equity-index futures/options expiry."""
    first = date(year, month, 1)
    first_friday = first + timedelta(days=(4 - first.weekday()) % 7)  # weekday: Fri == 4
    return first_friday + timedelta(days=14)


def front_month(root: str, on_date: date, *, exchange: str = "XCME") -> str:
    """The active front-month streamer symbol for ``root`` on ``on_date``.

    Returns e.g. ``/MESU26:XCME``. Picks the nearest quarterly contract whose roll
    date (expiry − 8 days) is still ahead — on/after the roll the next quarter is
    the liquid book. ``/scalp`` prep calls this so the once-a-quarter roll is a
    deterministic, date-driven choice, not a symbol you remember to hand-edit.
    """
    # Walk this year's and next year's quarterlies in order; take the first not yet rolled.
    for year in (on_date.year, on_date.year + 1):
        for month, code in _QUARTERLY_CODES.items():
            expiry = third_friday(year, month)
            if on_date < expiry - timedelta(days=_ROLL_DAYS):
                return f"{root}{code}{year % 100:02d}:{exchange}"
    raise ValueError(f"no front-month contract found for {root!r} on {on_date}")
