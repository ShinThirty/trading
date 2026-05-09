"""Shared types for prediction-market integrations.

Polymarket (crypto-settled, public CLOB) and Kalshi (CFTC-regulated, USD-settled)
expose conceptually identical data — a parent event with child markets that each
have an implied probability — but with very different schemas. This module defines
a common normalized representation so MCP tools and the regime classifier can
consume either source uniformly.
"""

from dataclasses import dataclass, field

from trading_clients.table_helpers import md_table


@dataclass
class PredictionOutcome:
    """One child market within a prediction-market event.

    label: human-readable outcome (e.g., "No change", "Above 3.50%")
    implied_prob: market-implied probability of YES, 0.0-1.0
    bid: yes-side bid in dollars (None if unavailable)
    ask: yes-side ask in dollars (None if unavailable)
    volume: lifetime traded volume; units differ by source (USD vs contracts)
    volume_24h: 24h traded volume; same caveat
    key: source-specific identifier (Polymarket conditionId / Kalshi market_ticker)
    """

    label: str
    implied_prob: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    volume_24h: float | None = None
    key: str = ""


@dataclass
class PredictionEvent:
    """A normalized prediction-market event with its outcomes.

    title: event title
    key: source-specific key (Polymarket slug / Kalshi event_ticker)
    end_date: ISO date the event resolves (best-effort string)
    source: "polymarket" or "kalshi"
    outcomes: child markets, ordered by descending implied probability
    """

    title: str = ""
    key: str = ""
    end_date: str = ""
    source: str = ""
    outcomes: list[PredictionOutcome] = field(default_factory=list)

    def to_output(self) -> str:
        if not self.outcomes:
            return f"(no outcomes for {self.source}:{self.key})"
        rows: list[list[str]] = []
        for o in self.outcomes:
            prob = f"{o.implied_prob * 100:.1f}%"
            spread = (
                f"{o.bid:.2f} / {o.ask:.2f}" if o.bid is not None and o.ask is not None else "—"
            )
            vol24 = f"{o.volume_24h:,.0f}" if o.volume_24h is not None else "—"
            rows.append([o.label, prob, spread, vol24])
        table = md_table(["Outcome", "Implied", "Bid / Ask", "Vol 24h"], rows)
        header = f"## {self.title}" if self.title else f"## {self.source}:{self.key}"
        meta = []
        if self.end_date:
            meta.append(f"resolves {self.end_date}")
        meta.append(f"source: {self.source}")
        meta.append(f"key: `{self.key}`")
        return "\n".join([header, "*" + " · ".join(meta) + "*", "", table])
