"""Yahoo Finance screener endpoint definitions with typed request/response models."""

from dataclasses import dataclass
from typing import Any

from trading_clients.endpoint import BodyRequest, Endpoint, ParamsRequest
from trading_clients.table_helpers import fmt_large, fmt_number, list_table

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class PredefinedScreenRequest(ParamsRequest):
    scr_id: str
    count: int = 25

    def to_params(self) -> dict[str, str]:
        return {"scrIds": self.scr_id, "count": str(self.count)}


@dataclass
class ScreenRequest(BodyRequest):
    criteria: list[dict[str, Any]]
    sort_field: str = "intradaymarketcap"
    sort_dir: str = "DESC"
    limit: int = 25
    offset: int = 0

    def to_body(self) -> dict[str, Any]:
        operands: list[dict[str, Any]] = [
            {"operator": "eq", "operands": ["region", "us"]},
        ]
        for c in self.criteria:
            op = c["op"]
            fld = c["field"]
            val = c["value"]
            if op == "btwn":
                operands.append({"operator": "btwn", "operands": [fld, val[0], val[1]]})
            elif op == "is-in":
                operands.append({"operator": "is-in", "operands": [fld, val]})
            else:
                operands.append({"operator": op, "operands": [fld, val]})
        return {
            "offset": self.offset,
            "size": self.limit,
            "sortField": self.sort_field,
            "sortType": self.sort_dir,
            "quoteType": "EQUITY",
            "query": {
                "operator": "and",
                "operands": operands,
            },
        }


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════


def _extract_result(data: dict) -> dict:
    results = data.get("finance", {}).get("result", [])
    return results[0] if results else {"quotes": [], "total": 0}


PREDEFINED_SCREEN = Endpoint(
    "/v1/finance/screener/predefined/saved",
    cache_ttl=900,
    response_model=ScreenerResponse,
    extract=_extract_result,
)

CUSTOM_SCREEN = Endpoint(
    "/v1/finance/screener",
    cache_ttl=0,
    response_model=ScreenerResponse,
    extract=_extract_result,
)
