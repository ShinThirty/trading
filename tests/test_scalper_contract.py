"""Verified contract resolution — the exchange names the contract *and* prices it.

The failures guarded against here are silent ones. A stale front month still streams,
still fires the detector, still fills the paper broker — on a book nobody is trading. A
wrong multiplier is the same failure in the P&L column: every number stays plausible. So
the month, the $/pt and the tick all come from the venue, and an unanswerable lookup
raises rather than guessing; there is deliberately no fallback.
"""

import asyncio

import pytest
from trading_clients.endpoints.tastytrade import FuturesResponse
from trading_scalper.contract import ContractError, product_code, resolve_contract
from trading_scalper.instruments import profile_for

# Shape of the real /instruments/futures?product-code[]=MES payload (trimmed to what we read).
_SEP = {
    "symbol": "/MESU6",
    "streamer-symbol": "/MESU26:XCME",
    "product-code": "MES",
    "exchange": "CME",
    "active-month": True,
    "next-active-month": False,
    "notional-multiplier": 5.0,
    "tick-size": 0.25,
    "expiration-date": "2026-09-18",
    "last-trade-date": "2026-09-18",
    "stops-trading-at": "2026-09-18T13:30:00.000+00:00",
    "roll-target-symbol": "/MESZ6",
    "is-tradeable": True,
    "is-closing-only": False,
}
_DEC = {
    **_SEP,
    "symbol": "/MESZ6",
    "streamer-symbol": "/MESZ26:XCME",
    "active-month": False,
    "next-active-month": True,
    "expiration-date": "2026-12-18",
    "last-trade-date": "2026-12-18",
    "roll-target-symbol": "/MESH7",
}


class FakeClient:
    """Stands in for TastyTradeClient.get — returns a canned contract set, or raises."""

    def __init__(self, items: list[dict] | None = None, *, error: Exception | None = None) -> None:
        self._items = items or []
        self._error = error
        self.calls: list[dict[str, str]] = []

    async def get(self, endpoint, request):  # noqa: ANN001 — duck-typed like BaseClient.get
        self.calls.append(request.to_params())
        if self._error is not None:
            raise self._error
        return FuturesResponse.from_response(self._items)


def test_product_code_drops_the_slash() -> None:
    assert product_code("/MES") == "MES"
    assert product_code("MES") == "MES"


def test_response_picks_the_active_month() -> None:
    resp = FuturesResponse.from_response([_DEC, _SEP])  # deliberately out of order
    front = resp.active_contract()
    assert front is not None
    assert front.streamer_symbol == "/MESU26:XCME"
    assert front.notional_multiplier == 5.0
    assert front.roll_target_symbol == "/MESZ6"
    assert resp.by_streamer_symbol("/MESZ26:XCME") is not None
    assert resp.by_streamer_symbol("/MESH27:XCME") is None


def test_response_will_not_offer_a_closing_only_contract() -> None:
    # active-month but restricted to closing orders: not something to open into
    resp = FuturesResponse.from_response([{**_SEP, "is-closing-only": True}])
    assert resp.active_contract() is None


def test_root_resolves_to_the_exchanges_front_month() -> None:
    client = FakeClient([_SEP, _DEC])
    got = asyncio.run(resolve_contract(client, "/MES"))

    assert got.symbol == "/MESU26:XCME"  # the exchange's active month, not a computed guess
    assert got.warnings == []
    assert got.point_value == 5.0 and got.tick == 0.25  # the exchange's, not typed in anywhere
    # calibration + level-source stay ours; the API has no opinion on them
    assert got.geometry is profile_for("/MES").geometry
    assert got.reference == "SPX"
    assert client.calls == [{"product-code[]": "MES", "only-active-futures": "true"}]


def test_stale_dated_symbol_warns_but_is_honored() -> None:
    # the plan named December on purpose; say it's draining, don't silently re-point it
    client = FakeClient([_SEP, _DEC])
    got = asyncio.run(resolve_contract(client, "/MESZ26:XCME"))

    assert got.symbol == "/MESZ26:XCME"
    assert any("NOT the active month" in w and "/MESU26:XCME" in w for w in got.warnings)


def test_closing_only_contract_warns() -> None:
    client = FakeClient([{**_SEP, "is-closing-only": True}])
    got = asyncio.run(resolve_contract(client, "/MESU26:XCME"))

    assert got.symbol == "/MESU26:XCME"
    assert any("closing-only" in w for w in got.warnings)


def test_economics_are_taken_verbatim_from_the_exchange() -> None:
    # nothing in the repo gets a vote: whatever the venue says is what the broker prices at
    client = FakeClient([{**_SEP, "notional-multiplier": 50.0, "tick-size": 0.5}])
    got = asyncio.run(resolve_contract(client, "/MES"))

    assert got.point_value == 50.0
    assert got.tick == 0.5
    assert got.warnings == []  # no second copy to disagree with, so nothing to reconcile


def test_fractional_multiplier_survives() -> None:
    # CME's micro Dow pays $0.50/pt — an int multiplier would floor it to zero and book
    # every trade as a $0 scratch
    client = FakeClient([{**_SEP, "notional-multiplier": 0.5}])
    got = asyncio.run(resolve_contract(client, "/MES"))

    assert got.point_value == 0.5


def test_unusable_economics_are_a_hard_stop() -> None:
    # a zero multiplier prices every fill at $0 — plausible-looking, entirely wrong
    client = FakeClient([{**_SEP, "notional-multiplier": 0.0}])
    with pytest.raises(ContractError, match="unusable economics"):
        asyncio.run(resolve_contract(client, "/MES"))


def test_api_failure_is_a_hard_stop() -> None:
    # no fallback: a guessed front month is indistinguishable from a real one until it's
    # cost you a session of garbage data on a dead book
    client = FakeClient(error=RuntimeError("no network"))
    with pytest.raises(ContractError, match="no network"):
        asyncio.run(resolve_contract(client, "/MES"))


def test_unknown_dated_symbol_is_a_hard_stop() -> None:
    client = FakeClient([_SEP, _DEC])  # the plan names a contract the exchange doesn't list
    with pytest.raises(ContractError, match="not in /MES's live contract set"):
        asyncio.run(resolve_contract(client, "/MESH26:XCME"))


def test_no_streamable_active_month_is_a_hard_stop() -> None:
    client = FakeClient([{**_SEP, "is-closing-only": True}, {**_DEC, "is-tradeable": False}])
    with pytest.raises(ContractError, match="no streamable active-month /MES contract"):
        asyncio.run(resolve_contract(client, "/MES"))


def test_nasdaq_root_gets_nasdaq_bands_and_ndx() -> None:
    # the profile follows the root even though the economics came off the wire
    client = FakeClient([{**_SEP, "symbol": "/MNQU6", "streamer-symbol": "/MNQU26:XCME"}])
    got = asyncio.run(resolve_contract(client, "/MNQ"))

    assert got.geometry is profile_for("/MNQ").geometry
    assert got.reference == "NDX"
