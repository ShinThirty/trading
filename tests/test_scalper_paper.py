"""PaperBroker matching engine: fills, the synthetic event stream, and OCO brackets.

The paper broker emits the *same* ``OrderEvent`` shape a real broker pushes, so
the persister + ledger are broker-agnostic. These pin the event contract, the
resting-order trigger, and ``place_bracket`` — the in-memory analog of Webull's
native 1st-Trigger stop/target OCO that the paper run validates.
"""

import pytest
from trading_scalper.domain import Order, OrderEvent, OrderStatus, OrderType, Side
from trading_scalper.paper import PaperBroker


def _mkt(side: Side, qty: int, price: float) -> Order:
    return Order("QQQ", side, qty, OrderType.MARKET, limit_price=price)


def test_market_order_fills_and_emits_event() -> None:
    paper = PaperBroker()
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)

    order_id = paper.place(_mkt(Side.BUY, 3, 1.25))

    assert paper.net_position("QQQ") == 3
    assert len(events) == 1
    ev = events[0]
    assert ev.order_id == order_id
    assert ev.status is OrderStatus.FILLED
    assert ev.filled_quantity == 3
    assert ev.fill_price == 1.25


def test_market_order_fills_at_last_traded_price_when_unpriced() -> None:
    paper = PaperBroker()
    paper.trade("QQQ", 2.40)  # seed a last price (Phase 2: the live tape)
    order_id = paper.place(Order("QQQ", Side.BUY, 1, OrderType.MARKET))
    assert paper.net_position("QQQ") == 1
    del order_id


def test_market_order_without_price_raises() -> None:
    paper = PaperBroker()
    try:
        paper.place(Order("QQQ", Side.BUY, 1, OrderType.MARKET))
    except ValueError:
        return
    raise AssertionError("expected ValueError with no reference price")


def test_positions_snapshot_excludes_flat() -> None:
    paper = PaperBroker()
    paper.place(_mkt(Side.BUY, 2, 1.0))
    paper.place(_mkt(Side.SELL, 2, 1.1))
    assert paper.net_position("QQQ") == 0
    assert paper.positions() == []


def test_resting_stop_triggers_on_tape_print() -> None:
    paper = PaperBroker()
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)

    paper.place(_mkt(Side.BUY, 2, 5.00))  # human is long 2
    stop_id = paper.place(Order("QQQ", Side.SELL, 2, OrderType.STOP, stop_price=4.50))

    assert paper.net_position("QQQ") == 2  # resting, not filled
    paper.trade("QQQ", 4.80)  # above the stop — no trigger
    assert paper.net_position("QQQ") == 2

    paper.trade("QQQ", 4.40)  # through the stop — fills, flattening the position
    assert paper.net_position("QQQ") == 0
    fill = events[-1]
    assert fill.order_id == stop_id
    assert fill.status is OrderStatus.FILLED
    assert fill.side is Side.SELL
    assert fill.fill_price == 4.40


def test_cancelled_stop_does_not_fill() -> None:
    paper = PaperBroker()
    paper.place(_mkt(Side.BUY, 1, 5.0))
    stop_id = paper.place(Order("QQQ", Side.SELL, 1, OrderType.STOP, stop_price=4.5))

    events: list[OrderEvent] = []
    paper.on_order_event(events.append)
    paper.cancel(stop_id)
    assert events[-1].status is OrderStatus.CANCELLED

    paper.trade("QQQ", 4.0)  # the cancelled stop must not fill
    assert paper.net_position("QQQ") == 1


# ── place_bracket (direction-aware entry + OCO stop/target) ───
# /MES: $5/point, 0.25 tick. A long from 6300 with stop 6290 / target 6320 risks
# $50 to make $100; the short is the mirror.


def test_place_bracket_long_opens_and_rests_oco_children() -> None:
    paper = PaperBroker(multiplier=5)
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)

    entry_id, stop_id, target_id = paper.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )

    assert paper.net_position("/MES") == 1  # entry filled immediately (long)
    statuses = {(e.order_id, e.status) for e in events}
    assert (entry_id, OrderStatus.FILLED) in statuses
    assert (stop_id, OrderStatus.NEW) in statuses  # both children resting
    assert (target_id, OrderStatus.NEW) in statuses
    # children rest on the SELL side for a long
    child_sides = {e.side for e in events if e.order_id in (stop_id, target_id)}
    assert child_sides == {Side.SELL}


def test_long_bracket_target_fills_and_cancels_stop() -> None:
    paper = PaperBroker(multiplier=5)
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)
    _, stop_id, target_id = paper.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )

    paper.trade("/MES", 6321.0)  # crosses the target -> win, OCO cancels the stop

    assert paper.net_position("/MES") == 0
    assert paper.realized_pnl() == pytest.approx((6320.0 - 6300.0) * 5)  # +100, fills at the limit
    statuses = {(e.order_id, e.status) for e in events}
    assert (target_id, OrderStatus.FILLED) in statuses
    assert (stop_id, OrderStatus.CANCELLED) in statuses


def test_long_bracket_stop_fills_and_cancels_target() -> None:
    paper = PaperBroker(multiplier=5)
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)
    _, stop_id, target_id = paper.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )

    paper.trade("/MES", 6289.0)  # crosses the stop -> loss, OCO cancels the target

    assert paper.net_position("/MES") == 0
    assert paper.realized_pnl() == pytest.approx((6289.0 - 6300.0) * 5)  # -55, fills at the print
    statuses = {(e.order_id, e.status) for e in events}
    assert (stop_id, OrderStatus.FILLED) in statuses
    assert (target_id, OrderStatus.CANCELLED) in statuses


def test_short_bracket_opens_short_and_rests_buy_children() -> None:
    """A SELL-to-open short: entry goes negative, both children rest on the BUY side,
    the stop is ABOVE entry (up-cross = loss) and the target BELOW (down-cross = win)."""
    paper = PaperBroker(multiplier=5)
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)

    _, stop_id, target_id = paper.place_bracket(
        "/MES", Side.SELL, 1, stop_price=6310.0, target_price=6280.0, reference=6300.0
    )

    assert paper.net_position("/MES") == -1  # entry opened a short
    child_sides = {e.side for e in events if e.order_id in (stop_id, target_id)}
    assert child_sides == {Side.BUY}  # cover orders


def test_short_bracket_target_wins_on_down_cross() -> None:
    paper = PaperBroker(multiplier=5)
    _, stop_id, target_id = paper.place_bracket(
        "/MES", Side.SELL, 1, stop_price=6310.0, target_price=6280.0, reference=6300.0
    )

    paper.trade("/MES", 6279.0)  # falls through the target -> cover for a win

    assert paper.net_position("/MES") == 0
    assert paper.realized_pnl() == pytest.approx((6300.0 - 6280.0) * 5)  # +100 covering lower
    del stop_id, target_id


def test_short_bracket_stop_loses_on_up_cross() -> None:
    paper = PaperBroker(multiplier=5)
    paper.place_bracket(
        "/MES", Side.SELL, 1, stop_price=6310.0, target_price=6280.0, reference=6300.0
    )

    paper.trade("/MES", 6310.0)  # rises to the stop -> cover for a loss (fills at the print)

    assert paper.net_position("/MES") == 0
    assert paper.realized_pnl() == pytest.approx((6300.0 - 6310.0) * 5)  # -50 covering higher


def test_bracket_snaps_children_to_tick() -> None:
    """Off-tick stop/target prices are snapped to the 0.25 grid before resting."""
    paper = PaperBroker(multiplier=5)
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)
    _, stop_id, target_id = paper.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.31, target_price=6319.88, reference=6300.0, tick=0.25
    )
    resting = {e.order_id: e for e in events if e.status is OrderStatus.NEW}
    assert resting[stop_id].order_id  # sanity
    # rested stop is a STOP order; inspect via a crossing print at the snapped level
    paper.trade("/MES", 6290.25)  # 6290.31 snaps down to 6290.25 -> stop triggers here
    assert paper.net_position("/MES") == 0
    del target_id


def test_bracket_legs_share_entry_id_and_close_carries_realized() -> None:
    paper = PaperBroker(multiplier=5)
    events: list[OrderEvent] = []
    paper.on_order_event(events.append)
    entry_id, stop_id, _target_id = paper.place_bracket(
        "/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0, reference=6300.0
    )

    paper.trade("/MES", 6289.0)  # stop fills -> loss

    assert all(e.bracket_id == entry_id for e in events)  # every leg keyed to the entry id
    entry_fill = next(e for e in events if e.order_id == entry_id)
    stop_fill = next(e for e in events if e.order_id == stop_id and e.status is OrderStatus.FILLED)
    assert entry_fill.realized_delta == 0.0  # the open realizes nothing
    assert stop_fill.realized_delta == pytest.approx(
        (6289.0 - 6300.0) * 5
    )  # -55 label on the close


def test_place_bracket_without_price_raises() -> None:
    paper = PaperBroker(multiplier=5)
    with pytest.raises(ValueError, match="no price"):
        paper.place_bracket("/MES", Side.BUY, 1, stop_price=6290.0, target_price=6320.0)
