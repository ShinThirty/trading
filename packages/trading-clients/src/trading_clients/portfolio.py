"""Multi-account portfolio aggregation and formatting.

Parses Fidelity CSVs and composes Webull API data into a consolidated
cross-account portfolio summary.
"""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_clients.table_helpers import fmt_number, list_table


def _safe_float(val: Any) -> float:
    """Parse a value to float, stripping commas and dollar signs."""
    if val is None or val == "" or val == "--":
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("+", ""))
    except (ValueError, TypeError):
        return 0.0


# Fidelity uses shortened OCC symbols: ROOT + YYMMDD + C/P + STRIKE (no zero-padding)
_FIDELITY_OPTION_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d+(?:\.\d+)?)$")


def parse_fidelity_option(symbol: str) -> tuple[str, str, str, float] | None:
    """Parse Fidelity option symbol into (underlying, expiration, option_type, strike).

    Fidelity format: ROOT + YYMMDD + C/P + STRIKE (no zero-padding).
    Example: 'COIN260515P160' → ('COIN', '2026-05-15', 'put', 160.0)
    Returns None if not an option symbol.
    """
    m = _FIDELITY_OPTION_RE.match(symbol)
    if not m:
        return None
    root, d, cp, strike = m.groups()
    exp = f"20{d[:2]}-{d[2:4]}-{d[4:6]}"
    option_type = "call" if cp == "C" else "put"
    return root, exp, option_type, float(strike)


@dataclass
class AccountSummary:
    account_id: str
    label: str
    broker: str  # "Webull" or "Fidelity"
    account_type: str  # "CASH", "MARGIN", etc.
    nlv: float = 0.0
    cash: float = 0.0
    market_value: float = 0.0
    day_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    positions: list[dict] = field(default_factory=list)


@dataclass
class PortfolioSummary:
    accounts: list[AccountSummary]
    errors: dict[str, str] = field(default_factory=dict)


_SKIP_SYMBOLS = {"BROKERAGELINK", "Totals", "Disclosure", ""}


def parse_fidelity_csv(path: str) -> AccountSummary:
    """Parse a single-account Fidelity positions CSV.

    Expected format:
    - Lines 1-3: title block (line 2 has account label)
    - Line 4: blank
    - Line 5: CSV header
    - Data rows until Totals
    - Totals row (Value column = NLV)
    - Disclosure section (ignored)
    """
    lines = Path(path).read_text().splitlines()

    # Extract account label from line 2
    label = lines[1].strip().strip('"') if len(lines) > 1 else Path(path).stem

    # Find header row (first row with "Symbol,")
    header_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("Symbol,"):
            header_idx = i
            break
    if header_idx < 0:
        return AccountSummary(
            account_id=Path(path).stem, label=label, broker="Fidelity", account_type="CASH"
        )

    # Parse CSV from header row onward
    reader = csv.DictReader(lines[header_idx:])
    positions: list[dict] = []
    cash = 0.0
    nlv = 0.0
    day_pnl = 0.0
    unrealized_pnl = 0.0

    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        if symbol in _SKIP_SYMBOLS or symbol.startswith('"'):
            if symbol == "Totals":
                nlv = _safe_float(row.get("Value"))
                day_pnl = _safe_float(row.get("$ Day G/L"))
                unrealized_pnl = _safe_float(row.get("$ Total G/L"))
            break  # Stop at Totals or Disclosure

        value = _safe_float(row.get("Value"))
        qty = _safe_float(row.get("Quantity"))
        last = _safe_float(row.get("Last"))
        cost = _safe_float(row.get("$ Avg Cost"))
        pnl = _safe_float(row.get("$ Total G/L"))
        pnl_pct = _safe_float(row.get("% Total G/L"))

        if symbol == "Cash (FDRXX)":
            cash = value
            positions.append(
                {
                    "symbol": "Cash (FDRXX)",
                    "quantity": qty,
                    "last": last,
                    "cost": cost,
                    "value": value,
                    "pnl": 0.0,
                    "pnl_pct": 0.0,
                    "is_option": False,
                    "is_cash": True,
                }
            )
            continue

        # Check if option
        opt = parse_fidelity_option(symbol)
        pos: dict[str, Any] = {
            "symbol": symbol,
            "quantity": qty,
            "last": last,
            "cost": cost,
            "value": value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "is_option": opt is not None,
            "is_cash": False,
        }
        if opt:
            underlying, exp, option_type, strike = opt
            pos["underlying"] = underlying
            pos["expiration"] = exp
            pos["option_type"] = option_type
            pos["strike"] = strike
            pos["earnings"] = row.get("Earnings Date", "").strip()

        positions.append(pos)

    return AccountSummary(
        account_id=Path(path).stem,
        label=label,
        broker="Fidelity",
        account_type="CASH",
        nlv=nlv,
        cash=cash,
        market_value=nlv - cash,
        day_pnl=day_pnl,
        unrealized_pnl=unrealized_pnl,
        positions=positions,
    )


def parse_fidelity_folder(folder: str) -> list[AccountSummary]:
    """Parse all Fidelity position CSVs in a folder."""
    folder_path = Path(folder).expanduser()
    if not folder_path.is_dir():
        return []
    csvs = sorted(folder_path.glob("Positions_*.csv"))
    return [parse_fidelity_csv(str(p)) for p in csvs]


def format_portfolio_summary(summary: PortfolioSummary) -> str:
    """Format a multi-account portfolio summary as markdown."""
    sections: list[str] = ["## Portfolio Summary", ""]

    # --- Account Balances ---
    acct_rows: list[dict[str, str]] = []
    total_nlv = 0.0
    total_cash = 0.0
    total_mv = 0.0
    total_day = 0.0
    total_unreal = 0.0

    for a in summary.accounts:
        acct_rows.append(
            {
                "Account": a.label,
                "Broker": a.broker,
                "NLV": fmt_number(a.nlv),
                "Cash": fmt_number(a.cash),
                "Market Value": fmt_number(a.market_value),
                "Day P&L": fmt_number(a.day_pnl),
                "Unrealized P&L": fmt_number(a.unrealized_pnl),
            }
        )
        total_nlv += a.nlv
        total_cash += a.cash
        total_mv += a.market_value
        total_day += a.day_pnl
        total_unreal += a.unrealized_pnl

    acct_rows.append(
        {
            "Account": "**Total**",
            "Broker": "",
            "NLV": f"**{fmt_number(total_nlv)}**",
            "Cash": f"**{fmt_number(total_cash)}**",
            "Market Value": f"**{fmt_number(total_mv)}**",
            "Day P&L": f"**{fmt_number(total_day)}**",
            "Unrealized P&L": f"**{fmt_number(total_unreal)}**",
        }
    )

    sections.append("### Account Balances")
    sections.append(list_table(acct_rows))
    sections.append("")

    # --- Option Positions ---
    option_rows: list[dict[str, str]] = []
    for a in summary.accounts:
        for p in a.positions:
            if not p.get("is_option"):
                continue
            row: dict[str, str] = {
                "Account": a.label,
                "Symbol": p.get("underlying", p["symbol"]),
                "Type": (p.get("option_type") or "")[0:1].upper(),
                "Strike": fmt_number(p.get("strike")),
                "Exp": p.get("expiration", ""),
                "Qty": fmt_number(p.get("quantity"), 0),
                "Cost": fmt_number(p.get("cost")),
                "Last": fmt_number(p.get("last")),
                "P&L": fmt_number(p.get("pnl")),
                "P&L %": fmt_number(p.get("pnl_pct")),
            }
            option_rows.append(row)

    if option_rows:
        sections.append(f"### Option Positions ({len(option_rows)} total)")
        sections.append(list_table(option_rows))
        sections.append("")

    # --- Equity Positions ---
    equity_rows: list[dict[str, str]] = []
    for a in summary.accounts:
        for p in a.positions:
            if p.get("is_option") or p.get("is_cash"):
                continue
            equity_rows.append(
                {
                    "Account": a.label,
                    "Symbol": p["symbol"],
                    "Qty": fmt_number(p.get("quantity"), 0),
                    "Cost": fmt_number(p.get("cost")),
                    "Last": fmt_number(p.get("last")),
                    "Mkt Val": fmt_number(p.get("value")),
                    "P&L": fmt_number(p.get("pnl")),
                    "P&L %": fmt_number(p.get("pnl_pct")),
                }
            )

    if equity_rows:
        sections.append(f"### Equity Positions ({len(equity_rows)} total)")
        sections.append(list_table(equity_rows))
        sections.append("")

    # --- Errors ---
    if summary.errors:
        sections.append("### Errors")
        for label, err in summary.errors.items():
            sections.append(f"- {label}: {err}")
        sections.append("")

    return "\n".join(sections)
