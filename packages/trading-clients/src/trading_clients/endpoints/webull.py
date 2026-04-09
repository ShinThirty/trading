"""Webull API v2 endpoint definitions with typed request/response models."""

from dataclasses import asdict, dataclass
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint, ParamsRequest
from trading_clients.table_helpers import fmt_number, kv_table, list_table

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

    def to_markdown(self) -> str:
        if not self.accounts:
            return "(no accounts)"
        rows = [
            {
                "Account ID": a.get("account_id", ""),
                "Account Number": a.get("account_number", ""),
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

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
        if not self.positions:
            return "(no positions)"
        has_options = any(p.get("legs") for p in self.positions)
        rows = []
        for p in self.positions:
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
                option_leg = next(
                    (lg for lg in p.get("legs", []) if lg.get("instrument_type") == "OPTION"),
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
        return list_table(rows, cols)


@dataclass
class InstrumentsResponse:
    instruments: list[dict]

    @classmethod
    def from_response(cls, data: list[dict]) -> "InstrumentsResponse":
        return cls(instruments=data or [])

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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

    def to_markdown(self) -> str:
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
