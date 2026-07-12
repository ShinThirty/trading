"""Instrument registry: point value ($/point) and tick size per futures symbol.

The scalper is instrument-agnostic below this table — the CLI looks up the
``point_value`` (the ``PaperBroker`` / ``Ledger`` multiplier) and ``tick`` (the
bracket-rounding grid) for the traded symbol here. ``/MES`` is the default paper
unit ($5/pt); ``/ES`` is the same contract at 10× ($50/pt).

A specific contract month from the data feed (e.g. ``/MESU25:XCME``) resolves to
its root's economics by prefix, so the plan can name either the continuous root
or a dated contract.
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
class Instrument:
    symbol: str
    point_value: int  # dollars per 1.0 index point per contract (the ledger multiplier)
    tick: float  # minimum price increment


# Insertion order matters for prefix resolution: longer roots (/MES, /MNQ) come
# before the shorter ones (/ES, /NQ) they'd otherwise shadow.
_INSTRUMENTS: dict[str, Instrument] = {
    "/MES": Instrument("/MES", 5, 0.25),  # Micro E-mini S&P 500
    "/MNQ": Instrument("/MNQ", 2, 0.25),  # Micro E-mini Nasdaq-100
    "/ES": Instrument("/ES", 50, 0.25),  # E-mini S&P 500
    "/NQ": Instrument("/NQ", 20, 0.25),  # E-mini Nasdaq-100
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
            return Instrument(symbol, base.point_value, base.tick)
    raise KeyError(f"unknown futures symbol {symbol!r}; known roots: {', '.join(_INSTRUMENTS)}")


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
