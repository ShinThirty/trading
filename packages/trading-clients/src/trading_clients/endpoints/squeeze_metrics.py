"""SqueezeMetrics public DIX/GEX CSV endpoint.

The /monitor/dix page renders a D3 chart from a public, no-auth CSV at
/monitor/static/DIX.csv. Updated once per trading day after market close.
Columns: date, price (S&P 500 close), DIX (Dark Index, 0-1 dollar-weighted
dark-pool short-volume ratio), GEX (dealer Gamma Exposure in raw dollars).

DIX is interpreted as dark-pool sentiment (higher = more bullish accumulation,
since dark-pool prints are reported as "short" by executing brokers regardless
of the ultimate buyer's direction). GEX captures dealer hedging posture
(positive = vol-suppressing, negative = vol-amplifying). Both are slow-moving
regime indicators — useful for the biweekly review macro section, not for
intraday tactics.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date

from trading_clients.endpoint import Endpoint, ParamsRequest


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class DixRow:
    """One trading-day observation: S&P 500 close + SqueezeMetrics DIX/GEX."""

    date: date
    price: float
    dix: float
    gex: float


@dataclass
class DixHistoryResponse:
    """Full DIX/GEX history. As of 2026-05 the file carries ~3,800 rows back
    to 2011-05-02; rows are sorted ascending by date."""

    rows: list[DixRow] = field(default_factory=list)

    @classmethod
    def from_response(cls, text: str) -> "DixHistoryResponse":
        rows: list[DixRow] = []
        reader = csv.DictReader(io.StringIO(text or ""))
        for r in reader:
            try:
                rows.append(
                    DixRow(
                        date=date.fromisoformat(r["date"]),
                        price=float(r["price"]),
                        dix=float(r["dix"]),
                        gex=float(r["gex"]),
                    )
                )
            except (KeyError, ValueError):
                continue
        rows.sort(key=lambda r: r.date)
        return cls(rows=rows)

    def to_output(self) -> str:
        if not self.rows:
            return "(no DIX history)"
        latest = self.rows[-1]
        return (
            f"DIX/GEX history: {len(self.rows)} rows from "
            f"{self.rows[0].date} to {latest.date}\n"
            f"Latest: SPX {latest.price:,.2f} DIX {latest.dix:.4f} "
            f"GEX {latest.gex:,.0f}"
        )


# 12-hour cache. The file is regenerated once per trading day after the close;
# refreshing more often than every few hours wastes bandwidth and serves the
# identical bytes. Within a single biweekly review, one fetch is enough.
DIX_HISTORY = Endpoint(
    "/monitor/static/DIX.csv",
    cache_ttl=12 * 3600,
    response_model=DixHistoryResponse,
)
