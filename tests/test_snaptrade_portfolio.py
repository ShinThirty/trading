"""SnapTrade → AccountSummary mapping.

SnapTrade replaces the Fidelity CSV as the source for Fidelity/NetBenefits
holdings. This pins the shape mapping the aggregation depends on: NLV from the
authoritative account balance, money-market flagged is_cash (excluded from
market value), short options kept as negative value at the ×100 multiplier, and
option underlying/type/strike parsed from the OCC ticker.
"""

from trading_clients.endpoints import snaptrade as ep
from trading_clients.snaptrade_portfolio import build_account_summary


def _positions(*rows: dict) -> ep.AccountPositionsResponse:
    return ep.AccountPositionsResponse.from_response(list(rows))


def _options(*rows: dict) -> ep.AccountOptionsResponse:
    return ep.AccountOptionsResponse.from_response(list(rows))


def _account(nlv: float) -> dict:
    return {
        "id": "acct-1",
        "name": "BrokerageLink",
        "number": "*****4787",
        "institution_name": "Fidelity",
        "account_category": "INVESTMENT",
        "raw_type": "NP",
        "balance": {"total": {"amount": nlv, "currency": {"code": "USD"}}},
    }


def _stock(ticker: str, units: float, price: float, cash: bool = False) -> dict:
    return {
        "symbol": {"symbol": {"symbol": ticker, "description": ticker}},
        "units": units,
        "price": price,
        "average_purchase_price": price,
        "open_pnl": 0.0,
        "cash_equivalent": cash,
    }


def _option(
    ticker: str, underlying: str, units: float, price: float, strike: float, exp: str
) -> dict:
    return {
        "symbol": {
            "option_symbol": {
                "ticker": ticker,
                "strike_price": strike,
                "expiration_date": exp,
                "underlying_symbol": {"symbol": underlying},
            }
        },
        "units": units,
        "price": price,
        "average_purchase_price": price,
    }


def test_maps_nlv_cash_and_market_value():
    acct = build_account_summary(
        _account(158_725.23),
        _positions(
            _stock("FDRXX", 80_000.0, 1.0, cash=True),  # money market → cash
            _stock("QCOM", 200, 189.16),
            _stock("ISRG", 100, 406.78),
        ),
        _options(),
    )
    assert acct.broker == "Fidelity"
    assert acct.account_type == "NP"
    assert acct.nlv == 158_725.23  # authoritative balance
    # market value = non-cash positions only; FDRXX excluded
    assert round(acct.market_value, 2) == round(200 * 189.16 + 100 * 406.78, 2)
    # cash absorbs the remainder so nlv == cash + market_value
    assert round(acct.cash + acct.market_value, 2) == 158_725.23


def test_short_option_is_negative_value_at_100x_and_excluded_from_long():
    acct = build_account_summary(
        _account(1_000.0),
        _positions(),
        _options(_option("SMCI  260710P00027500", "SMCI", -1, 0.01, 27.5, "2026-07-10")),
    )
    opt = acct.positions[0]
    assert opt["is_option"] is True
    assert opt["underlying"] == "SMCI"
    assert opt["option_type"] == "put"
    assert opt["strike"] == 27.5
    assert opt["quantity"] == -1
    assert round(opt["value"], 2) == -1.00  # -1 × 0.01 × 100
    # short option is a liability → not counted in long market value
    assert acct.market_value == round(-1.00, 2)


def test_call_option_type_parsed_from_ticker():
    acct = build_account_summary(
        _account(1_000.0),
        _positions(),
        _options(_option("AAPL  260117C00250000", "AAPL", 2, 5.0, 250.0, "2026-01-17")),
    )
    assert acct.positions[0]["option_type"] == "call"
    assert round(acct.positions[0]["value"], 2) == 1_000.00  # 2 × 5.0 × 100


def test_option_cost_basis_treats_avg_purchase_price_as_per_contract():
    # SnapTrade reports average_purchase_price PER CONTRACT (×100 baked in). A
    # per-share reading would exceed the strike on OTM shorts and multiply cost
    # basis — and thus P&L — by 100. This pins the real CRDO 7/10 short put that
    # produced a phantom +$582K "gain" before the fix.
    raw = {
        "symbol": {
            "option_symbol": {
                "ticker": "CRDO  260710P00250000",
                "strike_price": 250.0,
                "expiration_date": "2026-07-10",
                "underlying_symbol": {"symbol": "CRDO"},
            }
        },
        "units": -3,
        "price": 1.97,  # per share (last)
        "average_purchase_price": 1942.62,  # per contract (= $19.4262/share)
    }
    opt = ep.AccountOptionsResponse.from_response([raw]).to_normalized()[0]
    assert round(opt["cost"], 4) == 19.4262  # per-share cost, not 1942.62
    assert round(opt["value"], 2) == -591.00  # -3 × 1.97 × 100
    # cost_basis = 1942.62 × -3 = -5827.86 → pnl = -591 − (−5827.86) = +5236.86
    assert round(opt["pnl"], 2) == 5236.86  # sane ~90% capture, not +582,195


def test_zero_balance_account_has_no_positions():
    acct = build_account_summary(_account(0.0), _positions(), _options())
    assert acct.nlv == 0.0
    assert acct.positions == []
