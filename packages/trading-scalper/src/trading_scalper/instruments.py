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
