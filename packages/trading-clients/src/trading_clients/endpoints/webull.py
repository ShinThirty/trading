"""Webull API v2 endpoint definitions with typed request/response models."""

from dataclasses import asdict, dataclass
from typing import Any

from trading_clients.endpoint import CONTRACT_MULTIPLIER, BodyRequest, Endpoint, ParamsRequest
from trading_clients.portfolio import CASH_EQUIVALENTS
from trading_clients.table_helpers import fmt_number, kv_table, list_table


def _safe_float(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class EmptyRequest(ParamsRequest):
    """GET request with no parameters."""

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class AccountRequest(ParamsRequest):
    """GET request scoped to a single account."""

    account_id: str

    def to_params(self) -> dict[str, str]:
        return {"account_id": self.account_id}


@dataclass
class GetOpenOrdersRequest(ParamsRequest):
    account_id: str
    page_size: int = 50
    last_client_order_id: str | None = None

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "account_id": self.account_id,
            "page_size": str(self.page_size),
        }
        if self.last_client_order_id:
            params["last_client_order_id"] = self.last_client_order_id
        return params


@dataclass
class GetOrderHistoryRequest(ParamsRequest):
    account_id: str
    page_size: int = 50
    start_date: str | None = None
    end_date: str | None = None
    last_client_order_id: str | None = None

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "account_id": self.account_id,
            "page_size": str(self.page_size),
        }
        if self.start_date:
            params["start_date"] = self.start_date
        if self.end_date:
            params["end_date"] = self.end_date
        if self.last_client_order_id:
            params["last_client_order_id"] = self.last_client_order_id
        return params


@dataclass
class GetOrderDetailRequest(ParamsRequest):
    account_id: str
    client_order_id: str

    def to_params(self) -> dict[str, str]:
        return {"account_id": self.account_id, "client_order_id": self.client_order_id}


@dataclass
class GetInstrumentsRequest(ParamsRequest):
    symbols: str
    category: str = "US_STOCK"

    def to_params(self) -> dict[str, str]:
        return {"symbols": self.symbols, "category": self.category}


@dataclass
class PlaceOrderRequest(BodyRequest):
    account_id: str
    symbol: str
    side: str
    order_type: str
    quantity: str
    client_order_id: str
    time_in_force: str
    instrument_type: str = "EQUITY"
    combo_type: str = "NORMAL"
    market: str = "US"
    entrust_type: str = "QTY"
    trading_session: str = "CORE"
    limit_price: str | None = None
    stop_price: str | None = None
    trailing_type: str | None = None
    trailing_stop_step: str | None = None
    option_strategy: str | None = None
    position_intent: str | None = None
    legs: list[dict] | None = None

    def to_body(self) -> dict[str, Any]:
        order = {k: v for k, v in asdict(self).items() if v is not None and k != "account_id"}
        order["support_trading_session"] = order.pop("trading_session")
        return {"account_id": self.account_id, "new_orders": [order]}


@dataclass
class PreviewOrderRequest(PlaceOrderRequest):
    """Same structure as PlaceOrderRequest — preview before placing."""

    pass


@dataclass
class ReplaceOrderRequest(BodyRequest):
    account_id: str
    client_order_id: str
    quantity: str | None = None
    order_type: str | None = None
    time_in_force: str | None = None
    limit_price: str | None = None
    stop_price: str | None = None
    trailing_type: str | None = None
    trailing_stop_step: str | None = None

    def to_body(self) -> dict[str, Any]:
        modify = {k: v for k, v in asdict(self).items() if v is not None and k != "account_id"}
        return {"account_id": self.account_id, "modify_orders": [modify]}


@dataclass
class CancelOrderRequest(BodyRequest):
    account_id: str
    client_order_id: str

    def to_body(self) -> dict[str, Any]:
        return {"account_id": self.account_id, "client_order_id": self.client_order_id}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class AccountListResponse:
    accounts: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "AccountListResponse":
        return cls(accounts=data or [])

    def to_output(self) -> str:
        if not self.accounts:
            return "(no accounts)"
        rows = [
            {
                "Account ID": a.get("account_id", ""),
                "Type": a.get("account_type", ""),
                "Label": a.get("account_label", ""),
            }
            for a in self.accounts
        ]
        return list_table(rows)


@dataclass
class AccountBalanceResponse:
    net_liquidation: str
    market_value: str
    cash_balance: str
    day_pnl: str
    unrealized_pnl: str
    day_trades_left: str
    buying_power: str
    option_buying_power: str
    margin_ratio: str
    available_withdrawal: str

    @classmethod
    def from_response(cls, data: dict) -> "AccountBalanceResponse":
        if not data:
            return cls("", "", "", "", "", "", "", "", "", "")
        assets = data.get("account_currency_assets", [])
        usd = assets[0] if assets else {}
        return cls(
            net_liquidation=data.get("total_net_liquidation_value", ""),
            market_value=data.get("total_market_value", ""),
            cash_balance=data.get("total_cash_balance", ""),
            day_pnl=data.get("total_day_profit_loss", ""),
            unrealized_pnl=data.get("total_unrealized_profit_loss", ""),
            day_trades_left=data.get("day_trades_left", ""),
            buying_power=usd.get("buying_power", ""),
            option_buying_power=usd.get("option_buying_power", ""),
            margin_ratio=data.get("margin_ratio", ""),
            available_withdrawal=usd.get("available_withdrawal", ""),
        )

    def to_output(self) -> str:
        selected = {
            "Net Liquidation": fmt_number(self.net_liquidation),
            "Market Value": fmt_number(self.market_value),
            "Cash Balance": fmt_number(self.cash_balance),
            "Day P&L": fmt_number(self.day_pnl),
            "Unrealized P&L": fmt_number(self.unrealized_pnl),
            "Day Trades Left": self.day_trades_left,
            "Buying Power": fmt_number(self.buying_power),
            "Option Buying Power": fmt_number(self.option_buying_power),
            "Margin Ratio": self.margin_ratio,
            "Available Withdrawal": fmt_number(self.available_withdrawal),
        }
        return kv_table({k: v for k, v in selected.items() if v and v != "0.00"})


@dataclass
class PositionsResponse:
    positions: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "PositionsResponse":
        return cls(positions=data or [])

    def to_normalized(self) -> list[dict]:
        """Convert positions to normalized dicts for aggregation.

        Simple positions (0-1 legs) emit one entry.
        Multi-leg positions (covered stock, spreads) emit separate entries
        for each equity and option leg.

        Each dict has: symbol, quantity, last, cost, value, pnl, pnl_pct,
        is_option, is_cash. Option entries additionally have: underlying,
        option_type, strike, expiration, strategy.
        """
        sf = _safe_float
        result: list[dict] = []

        for p in self.positions:
            legs = p.get("legs", [])
            symbol = p.get("symbol", "")
            pnl_rate = p.get("unrealized_profit_loss_rate")
            pnl_pct = float(pnl_rate) * 100 if pnl_rate else 0.0

            if len(legs) <= 1:
                option_leg = next(
                    (lg for lg in legs if lg.get("instrument_type") == "OPTION"),
                    None,
                )
                is_cash_equiv = symbol in CASH_EQUIVALENTS
                pos: dict[str, Any] = {
                    "symbol": symbol,
                    "quantity": sf(p.get("quantity")),
                    "last": sf(p.get("last_price")),
                    "cost": sf(p.get("cost_price")),
                    "value": sf(p.get("market_value")),
                    "pnl": sf(p.get("unrealized_profit_loss")),
                    "pnl_pct": pnl_pct,
                    "is_option": option_leg is not None,
                    "is_cash": is_cash_equiv,
                }
                if option_leg:
                    pos["underlying"] = symbol
                    pos["option_type"] = (option_leg.get("option_type") or "").lower()
                    pos["strike"] = sf(option_leg.get("option_exercise_price"))
                    pos["expiration"] = option_leg.get("option_expire_date", "")
                    pos["strategy"] = p.get("option_strategy", "")
                result.append(pos)
            else:
                strategy = p.get("option_strategy", "")
                qty = sf(p.get("quantity"))
                for lg in legs:
                    itype = lg.get("instrument_type", "")
                    if itype == "EQUITY":
                        result.append(
                            {
                                "symbol": symbol,
                                "quantity": qty * CONTRACT_MULTIPLIER,
                                "last": sf(lg.get("last_price")),
                                "cost": sf(lg.get("cost")),
                                "value": sf(lg.get("last_price")) * qty * CONTRACT_MULTIPLIER,
                                "pnl": sf(lg.get("unrealized_profit_loss")),
                                "pnl_pct": 0.0,
                                "is_option": False,
                                "is_cash": False,
                            }
                        )
                    elif itype == "OPTION":
                        # Covered stock option legs are short — negate qty
                        opt_qty = -qty if strategy == "COVERED_STOCK" else qty
                        result.append(
                            {
                                "symbol": symbol,
                                "quantity": opt_qty,
                                "last": sf(lg.get("last_price")),
                                "cost": sf(lg.get("cost")),
                                "value": sf(lg.get("last_price")) * opt_qty * -CONTRACT_MULTIPLIER,
                                "pnl": sf(lg.get("unrealized_profit_loss")),
                                "pnl_pct": 0.0,
                                "is_option": True,
                                "is_cash": False,
                                "underlying": symbol,
                                "option_type": (lg.get("option_type") or "").lower(),
                                "strike": sf(lg.get("option_exercise_price")),
                                "expiration": lg.get("option_expire_date", ""),
                                "strategy": strategy,
                            }
                        )

        return result

    def to_output(self) -> str:
        if not self.positions:
            return "(no positions)"

        simple: list[dict] = []
        multi_leg: list[dict] = []
        for p in self.positions:
            if len(p.get("legs", [])) > 1:
                multi_leg.append(p)
            else:
                simple.append(p)

        sections: list[str] = []

        # Flat table for equity and single-leg option positions
        if simple:
            has_options = any(
                p.get("option_strategy") or p.get("instrument_type") == "OPTION" for p in simple
            )
            rows = []
            for p in simple:
                pnl_rate = p.get("unrealized_profit_loss_rate")
                pnl_pct = fmt_number(float(pnl_rate) * 100) if pnl_rate else ""
                row: dict[str, str] = {
                    "Symbol": p.get("symbol", ""),
                    "Qty": p.get("quantity", ""),
                    "Cost": fmt_number(p.get("cost_price")),
                    "Last": fmt_number(p.get("last_price")),
                    "Mkt Val": fmt_number(p.get("market_value")),
                    "P&L": fmt_number(p.get("unrealized_profit_loss")),
                    "P&L %": pnl_pct,
                }
                if has_options:
                    legs = p.get("legs", [])
                    option_leg = next(
                        (lg for lg in legs if lg.get("instrument_type") == "OPTION"),
                        None,
                    )
                    if option_leg:
                        row["Option"] = option_leg.get("option_type", "")
                        row["Strike"] = fmt_number(option_leg.get("option_exercise_price"))
                        row["Exp"] = option_leg.get("option_expire_date", "")
                    else:
                        row["Option"] = ""
                        row["Strike"] = ""
                        row["Exp"] = ""
                    row["Strategy"] = p.get("option_strategy", "")
                rows.append(row)
            cols = ["Symbol", "Qty", "Cost", "Last", "Mkt Val", "P&L", "P&L %"]
            if has_options:
                cols += ["Option", "Strike", "Exp", "Strategy"]
            sections.append(list_table(rows, cols))

        # Per-position tables for multi-leg positions
        for p in multi_leg:
            symbol = p.get("symbol", "")
            strategy = p.get("option_strategy", "")
            pnl = fmt_number(p.get("unrealized_profit_loss"))
            header = f"### {symbol} — {strategy}"
            if pnl:
                header += f" (P&L: {pnl})"

            leg_rows = []
            for lg in p.get("legs", []):
                itype = lg.get("instrument_type", "")
                if itype == "EQUITY":
                    leg_desc = "EQUITY"
                    qty = str(int(float(p.get("quantity", "0")) * 100))
                elif itype == "OPTION":
                    otype = lg.get("option_type", "")
                    strike = fmt_number(lg.get("option_exercise_price"))
                    exp = lg.get("option_expire_date", "")
                    leg_desc = f"{otype} {strike} {exp}"
                    qty = p.get("quantity", "")
                else:
                    leg_desc = itype
                    qty = ""
                leg_rows.append(
                    {
                        "Leg": leg_desc,
                        "Qty": qty,
                        "Cost": fmt_number(lg.get("cost")),
                        "Last": fmt_number(lg.get("last_price")),
                        "P&L": fmt_number(lg.get("unrealized_profit_loss")),
                    }
                )
            sections.append(header + "\n" + list_table(leg_rows))

        return "\n\n".join(sections)


@dataclass
class InstrumentsResponse:
    instruments: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "InstrumentsResponse":
        return cls(instruments=data or [])

    def to_output(self) -> str:
        if not self.instruments:
            return "(no instruments)"
        rows = [
            {
                "Symbol": i.get("symbol", ""),
                "Name": i.get("name", ""),
                "Instrument ID": i.get("instrument_id", ""),
                "Exchange": i.get("exchange_code", ""),
                "Currency": i.get("currency", ""),
                "Shortable": str(i.get("shortable", "")),
                "Fractionable": str(i.get("fractionable", "")),
            }
            for i in self.instruments
        ]
        return list_table(rows)


@dataclass
class OrderListResponse:
    combos: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "OrderListResponse":
        return cls(combos=data or [])

    def filter_by_status(self, status: str) -> "OrderListResponse":
        status_upper = status.upper()
        filtered = []
        for combo in self.combos:
            matching = [o for o in combo.get("orders", []) if o.get("status") == status_upper]
            if matching:
                filtered.append({**combo, "orders": matching})
        return OrderListResponse(combos=filtered)

    def to_output(self) -> str:
        if not self.combos:
            return "(no orders)"
        rows = []
        for combo in self.combos:
            for o in combo.get("orders", []):
                row: dict[str, str] = {
                    "Order ID": o.get("client_order_id", ""),
                    "Symbol": o.get("symbol", ""),
                    "Side": o.get("side", ""),
                    "Type": o.get("order_type", ""),
                    "Instrument": o.get("instrument_type", ""),
                    "Qty": o.get("total_quantity", ""),
                    "Filled": o.get("filled_quantity", ""),
                    "Price": fmt_number(o.get("limit_price")),
                    "Status": o.get("status", ""),
                    "Time": (o.get("place_time_at") or "")[:19],
                }
                legs = o.get("legs", [])
                if legs:
                    leg = legs[0]
                    row["Strike"] = fmt_number(leg.get("strike_price"))
                    row["Exp"] = leg.get("option_expire_date", "")
                    row["Option"] = leg.get("option_type", "")
                rows.append(row)
        return list_table(rows) if rows else "(no orders)"


@dataclass
class OrderDetailResponse:
    combo: dict

    @classmethod
    def from_response(cls, data: dict) -> "OrderDetailResponse":
        return cls(combo=data or {})

    def to_output(self) -> str:
        orders = self.combo.get("orders", [])
        if not orders:
            return "(no data)"
        sections = []
        for o in orders:
            details: dict[str, str | None] = {
                "Order ID": o.get("client_order_id"),
                "Symbol": o.get("symbol"),
                "Side": o.get("side"),
                "Type": o.get("order_type"),
                "Instrument": o.get("instrument_type"),
                "Qty": o.get("total_quantity"),
                "Filled": o.get("filled_quantity"),
                "Fill Price": fmt_number(o.get("filled_price")),
                "Limit": fmt_number(o.get("limit_price")),
                "Stop": fmt_number(o.get("stop_price")),
                "Status": o.get("status"),
                "TIF": o.get("time_in_force"),
                "Session": o.get("support_trading_session"),
                "Placed": (o.get("place_time_at") or "")[:19] or None,
                "Filled At": (o.get("filled_time_at") or "")[:19] or None,
            }
            legs = o.get("legs", [])
            if legs:
                leg = legs[0]
                details["Option"] = leg.get("option_type")
                details["Strike"] = fmt_number(leg.get("strike_price"))
                details["Exp"] = leg.get("option_expire_date")
            sections.append(kv_table({k: v for k, v in details.items() if v}))
        return "\n\n".join(sections)


@dataclass
class OrderResultResponse:
    data: dict

    @classmethod
    def from_response(cls, data: dict) -> "OrderResultResponse":
        return cls(data=data or {})

    def to_output(self) -> str:
        if not self.data:
            return "(no data)"
        return kv_table(self.data)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

ACCOUNT_LIST = Endpoint(
    "/openapi/account/list",
    cache_ttl=31536000,
    rate_key="account",
    response_model=AccountListResponse,
)

BALANCE = Endpoint(
    "/openapi/assets/balance",
    cache_ttl=60,
    rate_key="account",
    response_model=AccountBalanceResponse,
)

POSITIONS = Endpoint(
    "/openapi/assets/positions",
    cache_ttl=60,
    rate_key="account",
    response_model=PositionsResponse,
)

INSTRUMENTS = Endpoint(
    "/openapi/instrument/stock/list",
    cache_ttl=3600,
    rate_key="instruments",
    response_model=InstrumentsResponse,
)

OPEN_ORDERS = Endpoint(
    "/openapi/trade/order/open",
    cache_ttl=30,
    rate_key="order_read",
    response_model=OrderListResponse,
)

ORDER_HISTORY = Endpoint(
    "/openapi/trade/order/history",
    cache_ttl=30,
    rate_key="order_read",
    response_model=OrderListResponse,
)

ORDER_DETAIL = Endpoint(
    "/openapi/trade/order/detail",
    cache_ttl=30,
    rate_key="order_read",
    response_model=OrderDetailResponse,
)

PREVIEW_ORDER = Endpoint(
    "/openapi/trade/order/preview",
    rate_key="order_write",
    response_model=OrderResultResponse,
)

PLACE_ORDER = Endpoint(
    "/openapi/trade/order/place",
    rate_key="order_write",
    response_model=OrderResultResponse,
)

REPLACE_ORDER = Endpoint(
    "/openapi/trade/order/replace",
    rate_key="order_write",
    response_model=OrderResultResponse,
)

CANCEL_ORDER = Endpoint(
    "/openapi/trade/order/cancel",
    rate_key="order_write",
    response_model=OrderResultResponse,
)

# ═══════════════════════════════════════════════════════════════
# Crypto Market Data
# ═══════════════════════════════════════════════════════════════


@dataclass
class CryptoSnapshotRequest(ParamsRequest):
    symbols: str
    category: str = "US_CRYPTO"

    def to_params(self) -> dict[str, str]:
        return {"symbols": self.symbols, "category": self.category}


@dataclass
class CryptoBarsRequest(ParamsRequest):
    symbols: str
    timespan: str = "D"
    count: int = 200
    category: str = "US_CRYPTO"

    def to_params(self) -> dict[str, str]:
        return {
            "symbols": self.symbols,
            "category": self.category,
            "timespan": self.timespan,
            "count": str(self.count),
        }


@dataclass
class CryptoSnapshotResponse:
    snapshots: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "CryptoSnapshotResponse":
        return cls(snapshots=data or [])

    def to_output(self) -> str:
        if not self.snapshots:
            return "(no data)"
        rows: list[dict[str, str]] = []
        for s in self.snapshots:
            price = _safe_float(s.get("price"))
            change = _safe_float(s.get("change"))
            change_ratio = _safe_float(s.get("change_ratio")) * 100
            rows.append(
                {
                    "Symbol": s.get("symbol", ""),
                    "Price": fmt_number(price),
                    "Change": fmt_number(change),
                    "Change %": f"{change_ratio:+.2f}%",
                    "Open": fmt_number(s.get("open")),
                    "High": fmt_number(s.get("high")),
                    "Low": fmt_number(s.get("low")),
                    "Bid": fmt_number(s.get("bid")),
                    "Ask": fmt_number(s.get("ask")),
                }
            )
        return list_table(rows) if len(rows) > 1 else kv_table(rows[0])


@dataclass
class CryptoBarsResponse:
    bars: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "CryptoBarsResponse":
        if data and isinstance(data, list) and data[0].get("result"):
            return cls(bars=data[0]["result"])
        return cls(bars=[])

    def to_output(self) -> str:
        if not self.bars:
            return "(no data)"
        rows = [
            {
                "Time": b.get("time", "")[:10],
                "Open": fmt_number(b.get("open")),
                "High": fmt_number(b.get("high")),
                "Low": fmt_number(b.get("low")),
                "Close": fmt_number(b.get("close")),
            }
            for b in self.bars
        ]
        return list_table(rows)


CRYPTO_SNAPSHOT = Endpoint(
    "/openapi/market-data/crypto/snapshot",
    cache_ttl=30,
    rate_key="default",
    response_model=CryptoSnapshotResponse,
)

CRYPTO_BARS = Endpoint(
    "/openapi/market-data/crypto/bars",
    cache_ttl=300,
    rate_key="default",
    response_model=CryptoBarsResponse,
)
