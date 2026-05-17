"""Market regime classification.

Pure functions that classify market conditions into simple labels
from pre-fetched data. No I/O — all data fetching happens in the
MCP server layer.

Organized by dimension; this __init__ re-exports the public surface so
callers can keep using `from trading_clients import regime` and reach
`regime.classify_volatility`, `regime.score_bear_curve`, etc.
"""

from ._common import parse_fred_value
from .bear_score import (
    BearScoreComponent,
    score_bear_breadth,
    score_bear_credit,
    score_bear_curve,
    score_bear_dealer_flow,
    score_bear_positioning,
    score_bear_sentiment,
    score_bear_technicals,
    score_bear_valuation,
    score_bear_volatility,
    synthesize_bear_regime,
)
from .breadth import classify_breadth
from .credit import classify_credit, detect_credit_trap
from .curve import classify_curve_regime, classify_macro, detect_uninversion_trap
from .policy import classify_policy, synthesize_policy_path
from .sectors import (
    RISK_OFF_ETFS,
    RISK_ON_ETFS,
    SECTOR_ETFS,
    classify_sector_rotation,
    detect_semi_divergence,
)
from .sentiment import classify_positioning, classify_sentiment
from .trend import classify_extended, classify_trend
from .valuation import classify_erp
from .verdict import synthesize_verdict
from .volatility import classify_tape_speed, classify_volatility

__all__ = [
    "BearScoreComponent",
    "RISK_OFF_ETFS",
    "RISK_ON_ETFS",
    "SECTOR_ETFS",
    "classify_breadth",
    "classify_credit",
    "classify_curve_regime",
    "classify_erp",
    "classify_extended",
    "classify_macro",
    "classify_policy",
    "classify_positioning",
    "classify_sector_rotation",
    "classify_sentiment",
    "classify_tape_speed",
    "classify_trend",
    "classify_volatility",
    "detect_credit_trap",
    "detect_semi_divergence",
    "detect_uninversion_trap",
    "parse_fred_value",
    "score_bear_breadth",
    "score_bear_credit",
    "score_bear_curve",
    "score_bear_dealer_flow",
    "score_bear_positioning",
    "score_bear_sentiment",
    "score_bear_technicals",
    "score_bear_valuation",
    "score_bear_volatility",
    "synthesize_bear_regime",
    "synthesize_policy_path",
    "synthesize_verdict",
]
