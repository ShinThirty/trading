"""Local paper entry-detector for intraday index-futures (/MES) scalps.

See docs/scalper-automation.md. The daemon detects a setup off the live futures
tape, prompts the human, and auto-executes the same direction-aware bracket in an
in-memory ``PaperBroker`` — persisting fills + a P&L summary so the detector's
track record is reviewable. Paper-only: no real capital is ever at risk.
"""

from trading_clients.market_stream import MarketEvent, Quote, TimeSale, Trade

from trading_scalper.cli import (
    ScalpSession,
    build_session,
    collect_symbols,
    make_executor,
)
from trading_scalper.detector import SetupDetector, watch_setups
from trading_scalper.domain import (
    Order,
    OrderEvent,
    OrderEventCallback,
    OrderId,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TradeProposal,
)
from trading_scalper.feed import DxLinkFeed, drive_paper_fills
from trading_scalper.ledger import Ledger
from trading_scalper.notify import Notifier
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import (
    PaperPersister,
    default_fills_path,
    default_summary_path,
    summarize_fills,
)
from trading_scalper.plan import Level, PlanStore, SessionPlan, default_plan_path, load_session_plan
from trading_scalper.ports import BrokerExecution, MarketDataFeed

__all__ = [
    "BrokerExecution",
    "Ledger",
    "Level",
    "MarketDataFeed",
    "MarketEvent",
    "Notifier",
    "Order",
    "OrderEvent",
    "OrderEventCallback",
    "OrderId",
    "OrderStatus",
    "OrderType",
    "PaperBroker",
    "PaperPersister",
    "PlanStore",
    "Position",
    "Quote",
    "ScalpSession",
    "SessionPlan",
    "SetupDetector",
    "Side",
    "TimeSale",
    "DxLinkFeed",
    "Trade",
    "TradeProposal",
    "build_session",
    "collect_symbols",
    "default_fills_path",
    "default_plan_path",
    "default_summary_path",
    "drive_paper_fills",
    "load_session_plan",
    "make_executor",
    "summarize_fills",
    "watch_setups",
]
