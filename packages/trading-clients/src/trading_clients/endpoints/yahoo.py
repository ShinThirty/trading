"""Yahoo Finance response models for output formatting."""

from dataclasses import dataclass

from trading_clients.table_helpers import fmt_large, fmt_number, list_table


@dataclass
class ScreenerResponse:
    quotes: list[dict]
    total: int

    @classmethod
    def from_response(cls, data: dict) -> "ScreenerResponse":
        return cls(
            quotes=data.get("quotes", []),
            total=data.get("total", 0),
        )

    def to_output(self) -> str:
        if not self.quotes:
            return "(no results)"
        rows = [
            {
                "Symbol": q.get("symbol", ""),
                "Name": (q.get("longName") or q.get("shortName") or "")[:30],
                "Price": fmt_number(q.get("regularMarketPrice")),
                "Chg%": fmt_number(q.get("regularMarketChangePercent")),
                "Mkt Cap": fmt_large(q.get("marketCap")),
                "P/E": fmt_number(q.get("trailingPE"), 1),
                "Volume": fmt_large(q.get("regularMarketVolume")),
                "Sector": (q.get("sector") or "")[:15],
            }
            for q in self.quotes
        ]
        header = f"Showing {len(self.quotes)} of {self.total} results\n\n"
        return header + list_table(rows)
