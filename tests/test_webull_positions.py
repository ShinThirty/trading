"""COVERED_STOCK normalization: covered calls vs protective (married) puts.

Webull returns a covered call (long stock + short call) and a protective put
(long stock + long put) under the same `COVERED_STOCK` strategy. The only thing
that distinguishes them is the option type, so `to_normalized()` must sign the
option leg by type — call = short, put = long — not assume every leg is short.
"""

from trading_clients.endpoints.webull import PositionsResponse


def _covered_call_position() -> dict:
    """Long 300 shares META + short 3x 640 call (like the live book)."""
    return {
        "symbol": "META",
        "option_strategy": "COVERED_STOCK",
        "quantity": "3",
        "unrealized_profit_loss_rate": "0",
        "legs": [
            {
                "instrument_type": "EQUITY",
                "last_price": "619.66",
                "cost": "628.77",
                "unrealized_profit_loss": "-2733",
            },
            {
                "instrument_type": "OPTION",
                "option_type": "CALL",
                "option_exercise_price": "640",
                "option_expire_date": "2026-06-05",
                "last_price": "2.38",
                "cost": "5.45",
                "unrealized_profit_loss": "921",
            },
        ],
    }


def _protective_put_position() -> dict:
    """Long 100 shares AVGO + long 1x 465 put (the married-put hedge)."""
    return {
        "symbol": "AVGO",
        "option_strategy": "COVERED_STOCK",
        "quantity": "1",
        "unrealized_profit_loss_rate": "0",
        "legs": [
            {
                "instrument_type": "EQUITY",
                "last_price": "415.90",
                "cost": "341.79",
                "unrealized_profit_loss": "7411",
            },
            {
                "instrument_type": "OPTION",
                "option_type": "PUT",
                "option_exercise_price": "465",
                "option_expire_date": "2026-06-12",
                "last_price": "17.85",
                "cost": "15.35",
                "unrealized_profit_loss": "250",
            },
        ],
    }


def _option_entry(normalized: list[dict]) -> dict:
    return next(p for p in normalized if p["is_option"])


def _equity_entry(normalized: list[dict]) -> dict:
    return next(p for p in normalized if not p["is_option"])


def test_covered_call_leg_is_short():
    norm = PositionsResponse([_covered_call_position()]).to_normalized()
    call = _option_entry(norm)
    assert call["option_type"] == "call"
    # Short call: negative contracts and negative (liability) market value.
    assert call["quantity"] == -3
    assert call["value"] == 2.38 * -3 * 100
    assert call["value"] < 0
    # Equity leg keeps full long share count.
    assert _equity_entry(norm)["quantity"] == 300


def test_protective_put_leg_is_long():
    norm = PositionsResponse([_protective_put_position()]).to_normalized()
    put = _option_entry(norm)
    assert put["option_type"] == "put"
    # Long put: positive contracts and positive (asset) market value — the bug
    # forced this negative, mislabeling the hedge as a short put.
    assert put["quantity"] == 1
    assert put["value"] == 17.85 * 1 * 100
    assert put["value"] > 0
    assert _equity_entry(norm)["quantity"] == 100


def test_protective_put_not_counted_as_csp_collateral():
    """A long put must not look like a short CSP (qty >= 0 -> no collateral)."""
    norm = PositionsResponse([_protective_put_position()]).to_normalized()
    put = _option_entry(norm)
    # _compute_csp_collateral only charges collateral for puts with qty < 0.
    assert put["option_type"] == "put"
    assert put["quantity"] >= 0
