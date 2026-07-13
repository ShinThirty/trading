"""Verified contract resolution — ask the exchange what we're trading, and what it's worth.

``GET /instruments/futures?product-code[]=MES`` returns every live contract with its
``active-month`` flag, dxFeed ``streamer-symbol``, ``notional-multiplier`` and
``tick-size``. That is the whole economic description of the thing we clear against, so
it is the *only* source for it: which month is live, what a point pays, what a tick is.
None of the three is typed into this repo.

**A failed lookup is a hard stop, not a fallback.** The date math this replaced was
usually right, which is exactly what made it dangerous: when it was wrong it failed
*silently* — a stale front month still streams, still fires the detector, still fills the
paper broker, on a drying-up book, producing a session of data that looks fine and isn't.
A wrong multiplier is the same failure in the P&L column: every number stays plausible.
A guess that can't be distinguished from the truth is worse than no session, so when the
exchange won't tell us what to trade, we don't trade.

``instruments.py`` keeps only what the API has no opinion about — the detector's
``Geometry`` bands (our calibration) and the cash-index ``reference`` (our level-source
decision). This module joins the two: exchange economics + our profile.
"""

from dataclasses import dataclass, field

from trading_clients.endpoints.tastytrade import FUTURES, FuturesRequest
from trading_clients.tastytrade_client import TastyTradeClient

from trading_scalper.instruments import Geometry, profile_for, root_of


class ContractError(RuntimeError):
    """The exchange could not tell us what to trade — stop, never guess."""


@dataclass(frozen=True, slots=True)
class ResolvedContract:
    """One live futures contract: the exchange's economics, our calibration."""

    symbol: str  # dxFeed streamer symbol to subscribe (e.g. /MESU26:XCME)
    point_value: float  # $ per 1.0 index point — the exchange's notional-multiplier
    tick: float  # minimum price increment — the exchange's tick-size
    geometry: Geometry  # ours: the detector's price-distance bands
    reference: str  # ours: cash-index for the gamma walls + carry basis (SPX / NDX)
    warnings: list[str] = field(default_factory=list)


def product_code(root: str) -> str:
    """``/MES`` → ``MES`` — the API's product-code param drops the leading slash."""
    return root.lstrip("/")


async def resolve_contract(client: TastyTradeClient, symbol: str) -> ResolvedContract:
    """Resolve ``symbol`` (a root like ``/MES``, or a dated streamer symbol) to what to stream.

    A **root** resolves to the exchange's ``active-month`` contract. A **dated symbol** is
    taken as given but checked against the live set — streaming a contract that is no
    longer the front month, or is closing-only, is exactly the silent failure this exists
    to catch, so it warns rather than overrides (the plan named that contract on purpose).

    Raises :class:`ContractError` when the exchange can't answer — no creds, network down,
    an unknown product, a symbol not in the live set. There is deliberately no fallback:
    see the module docstring.
    """
    root = root_of(symbol)
    profile = profile_for(symbol)  # raises KeyError on a root we have no geometry for
    dated = ":" in symbol  # a dxFeed streamer symbol, not a bare root

    try:
        resp = await client.get(FUTURES, FuturesRequest(product_code(root)))
    except Exception as exc:  # noqa: BLE001 — every failure mode lands the same way: stop
        raise ContractError(
            f"contract lookup for {symbol} failed ({type(exc).__name__}: {exc}). "
            "No session — trading a contract nobody confirmed is live is the silent "
            "failure this check exists to prevent."
        ) from exc

    contract = resp.by_streamer_symbol(symbol) if dated else resp.active_contract()
    if contract is None:
        raise ContractError(
            f"{symbol} is not in {root}'s live contract set (expired? wrong exchange?)"
            if dated
            else f"no streamable active-month {root} contract in the exchange's response "
            "(every listed contract is untradeable or closing-only)"
        )
    if contract.notional_multiplier <= 0 or contract.tick_size <= 0:
        raise ContractError(
            f"{contract.streamer_symbol} came back with unusable economics "
            f"(${contract.notional_multiplier}/pt, {contract.tick_size} tick) — refusing to "
            "price a paper session off them."
        )

    warnings: list[str] = []
    if dated and not contract.active_month:
        front = resp.active_contract()
        warnings.append(
            f"{symbol} is NOT the active month — the exchange's front contract is "
            f"{front.streamer_symbol if front else '(none)'}. You are streaming a draining book."
        )
    if not contract.streamable:
        warnings.append(
            f"{symbol} is closing-only or untradeable (last trade {contract.last_trade_date}) — "
            "no new positions should be opened in it."
        )
    return ResolvedContract(
        symbol=contract.streamer_symbol,
        point_value=contract.notional_multiplier,
        tick=contract.tick_size,
        geometry=profile.geometry,
        reference=profile.reference,
        warnings=warnings,
    )
