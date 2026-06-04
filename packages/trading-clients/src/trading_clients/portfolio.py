"""Multi-account portfolio aggregation and formatting.

Parses Fidelity CSVs and composes Webull API data into a consolidated
cross-account portfolio summary.
"""

import asyncio
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_clients.table_helpers import fmt_number, list_table

CASH_EQUIVALENTS = {"FDRXX", "SGOV"}


def _safe_float(val: Any) -> float:
    """Parse a value to float, stripping commas, dollar signs, and percent signs."""
    if val is None or val == "" or val == "--":
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("+", "").replace("%", ""))
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


_FIDELITY_REQUIRED_COLUMNS = {
    "Account Number",
    "Account Name",
    "Symbol",
    "Quantity",
    "Last Price",
    "Current Value",
    "Average Cost Basis",
    "Total Gain/Loss Dollar",
    "Total Gain/Loss Percent",
    "Today's Gain/Loss Dollar",
}


class FidelityFormatError(ValueError):
    """Raised when a Fidelity CSV doesn't match the expected format."""


async def parse_fidelity_csv(path: str) -> list[AccountSummary]:
    """Parse a Fidelity positions CSV into one summary per account.

    Handles the current Fidelity export format:
    - Row 1: CSV header (Account Number, Account Name, Symbol, ...)
    - Data rows with account info in each row. A single export commonly
      contains several accounts (BrokerageLink, Roth, HSA, 401k, ...); each
      distinct Account Number becomes its own AccountSummary.
    - No-ticker core/sweep rows (e.g. a BrokerageLink core balance, which has
      an empty Symbol but a real Current Value) are counted as cash.
    - Trailing blank line + disclaimer text at the bottom (ignored).

    Raises FidelityFormatError if the CSV format is unrecognized.
    """
    text = (await asyncio.to_thread(Path(path).read_text, encoding="utf-8-sig")).splitlines()

    # Find header row
    header_idx = -1
    for i, line in enumerate(text):
        if "Symbol" in line and "," in line:
            header_idx = i
            break
    if header_idx < 0:
        raise FidelityFormatError(
            f"No CSV header row found in {Path(path).name}. "
            "Expected a row containing 'Symbol' and other column headers."
        )

    reader = csv.DictReader(text[header_idx:])
    columns = set(reader.fieldnames or [])
    missing = _FIDELITY_REQUIRED_COLUMNS - columns
    if missing:
        raise FidelityFormatError(
            f"Fidelity CSV format changed — {Path(path).name} is missing columns: "
            f"{', '.join(sorted(missing))}. "
            f"Found columns: {', '.join(sorted(columns))}"
        )

    stem = Path(path).stem
    accounts: dict[str, AccountSummary] = {}

    def _account_for(number: str, name: str) -> AccountSummary:
        acct = accounts.get(number)
        if acct is None:
            acct = AccountSummary(
                account_id=number or stem,
                label=name or number or stem,
                broker="Fidelity",
                account_type="CASH",
            )
            accounts[number] = acct
        return acct

    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        account_number = (row.get("Account Number") or "").strip()
        account_name = (row.get("Account Name") or "").strip()
        current_value_raw = (row.get("Current Value") or "").strip()

        # A row with no Symbol is one of three things:
        #   1. A roll-up pointer (Description "BROKERAGELINK") whose underlying
        #      holdings are enumerated separately under their own Account
        #      Numbers — e.g. a 401k whose BrokerageLink sub-accounts are
        #      listed as distinct accounts later in the file. Counting it would
        #      double-count those sub-accounts, so skip it.
        #   2. A genuine no-ticker core/sweep cash balance — count as cash.
        #   3. The trailing blank line / disclaimer text — end of holdings.
        # The core balance and roll-up both carry an Account Number AND a
        # Current Value; the disclaimer/blank rows carry neither — so use that
        # to find the end of holdings instead of breaking on the first empty
        # Symbol (which silently dropped the entire file when a no-Symbol line
        # came first).
        if not symbol:
            if not account_number or not current_value_raw:
                break  # blank line or disclaimer — end of holdings
            description = (row.get("Description") or "").strip()
            if description.upper() == "BROKERAGELINK":
                continue  # roll-up of sub-accounts enumerated separately
            acct = _account_for(account_number, account_name)
            value = _safe_float(current_value_raw)
            acct.cash += value
            acct.positions.append(
                {
                    "symbol": description or "Core",
                    "quantity": _safe_float(row.get("Quantity")),
                    "last": _safe_float(row.get("Last Price")),
                    "cost": _safe_float(row.get("Average Cost Basis")),
                    "value": value,
                    "pnl": _safe_float(row.get("Total Gain/Loss Dollar")),
                    "pnl_pct": _safe_float(row.get("Total Gain/Loss Percent")),
                    "is_option": False,
                    "is_cash": True,
                }
            )
            continue

        acct = _account_for(account_number, account_name)

        # Normalize: strip trailing asterisks (e.g. FDRXX** → FDRXX)
        symbol = symbol.rstrip("*")

        # Handle pending activity as cash adjustment (unsettled transactions)
        if symbol.lower() == "pending activity":
            acct.cash += _safe_float(row.get("Current Value"))
            continue

        # Handle cash / money market / cash equivalents
        if symbol in CASH_EQUIVALENTS:
            value = _safe_float(row.get("Current Value"))
            acct.cash += value
            acct.positions.append(
                {
                    "symbol": symbol,
                    "quantity": _safe_float(row.get("Quantity")),
                    "last": _safe_float(row.get("Last Price")),
                    "cost": _safe_float(row.get("Average Cost Basis")),
                    "value": value,
                    "pnl": _safe_float(row.get("Total Gain/Loss Dollar")),
                    "pnl_pct": _safe_float(row.get("Total Gain/Loss Percent")),
                    "is_option": False,
                    "is_cash": True,
                }
            )
            continue

        # Strip leading " -" prefix on short option symbols
        clean_symbol = symbol.lstrip(" -")

        value = _safe_float(row.get("Current Value"))
        qty = _safe_float(row.get("Quantity"))
        last = _safe_float(row.get("Last Price"))
        cost = _safe_float(row.get("Average Cost Basis"))
        pnl = _safe_float(row.get("Total Gain/Loss Dollar"))
        pnl_pct = _safe_float(row.get("Total Gain/Loss Percent"))
        acct.day_pnl += _safe_float(row.get("Today's Gain/Loss Dollar"))
        acct.unrealized_pnl += pnl

        opt = parse_fidelity_option(clean_symbol)
        pos: dict[str, Any] = {
            "symbol": clean_symbol,
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

        acct.positions.append(pos)

    for acct in accounts.values():
        acct.market_value = sum(
            p.get("value", 0.0) for p in acct.positions if not p.get("is_cash")
        )
        acct.nlv = acct.cash + acct.market_value

    return list(accounts.values())


async def parse_fidelity_folder(folder: str) -> list[AccountSummary]:
    """Parse all Fidelity position CSVs in a folder."""
    folder_path = Path(folder).expanduser()
    if not folder_path.is_dir():
        return []
    csvs = sorted(folder_path.glob("*Positions*.csv"))
    per_file = await asyncio.gather(*(parse_fidelity_csv(str(p)) for p in csvs))
    return [acct for file_accounts in per_file for acct in file_accounts]


def compact_portfolio_summary(summary: PortfolioSummary, file_path: str) -> str:
    """Return a brief summary line with a pointer to the full details file."""
    total_nlv = sum(a.nlv for a in summary.accounts)
    total_day = sum(a.day_pnl for a in summary.accounts)
    n_accounts = len(summary.accounts)
    n_options = sum(1 for a in summary.accounts for p in a.positions if p.get("is_option"))
    n_equity = sum(
        1
        for a in summary.accounts
        for p in a.positions
        if not p.get("is_option") and not p.get("is_cash")
    )
    sign = "+" if total_day >= 0 else ""
    lines = [
        f"Portfolio: ${fmt_number(total_nlv)} across {n_accounts} accounts"
        f" ({sign}${fmt_number(total_day)} day)",
        f"{n_options} option positions, {n_equity} equity positions",
        f"Full details: {file_path}",
    ]
    if summary.errors:
        lines.append(f"Errors: {', '.join(summary.errors.keys())}")
    return "\n".join(lines)


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


def format_greeks_compact(totals: dict, n_options: int, detail_path: str) -> str:
    """Format a compact portfolio Greeks summary with pointer to detail file."""
    d_sign = "+" if totals["delta"] >= 0 else ""
    t_sign = "+" if totals["theta"] >= 0 else ""
    v_sign = "+" if totals["vega"] >= 0 else ""
    return (
        f"Portfolio Greeks ({n_options} option positions)\n"
        f"Net Delta: {d_sign}{fmt_number(totals['delta'], 0)}"
        f" (≈${d_sign}{fmt_number(totals['delta'], 0)} per $1 move)\n"
        f"Net Theta: {t_sign}${fmt_number(totals['theta'])}/day\n"
        f"Net Gamma: {fmt_number(totals['gamma'], 0)}\n"
        f"Net Vega:  {v_sign}${fmt_number(totals['vega'])} per 1% IV move\n"
        f"Full details: {detail_path}"
    )


def format_greeks_detail(totals: dict, by_underlying: dict) -> str:
    """Format a detailed per-underlying Greeks breakdown as markdown."""
    d_sign = "+" if totals["delta"] >= 0 else ""
    t_sign = "+" if totals["theta"] >= 0 else ""
    v_sign = "+" if totals["vega"] >= 0 else ""

    sections = [
        "## Portfolio Greeks Detail",
        "",
        "### Summary",
        f"- Net Delta: {d_sign}{fmt_number(totals['delta'], 0)}",
        f"- Net Theta: {t_sign}${fmt_number(totals['theta'])}/day",
        f"- Net Gamma: {fmt_number(totals['gamma'], 0)}",
        f"- Net Vega: {v_sign}${fmt_number(totals['vega'])}",
        "",
    ]

    underlying_rows = []
    for sym in sorted(by_underlying, key=lambda s: abs(by_underlying[s]["delta"]), reverse=True):
        u = by_underlying[sym]
        underlying_rows.append(
            {
                "Symbol": sym,
                "Delta": fmt_number(u["delta"], 0),
                "Theta": fmt_number(u["theta"]),
                "Gamma": fmt_number(u["gamma"], 0),
                "Vega": fmt_number(u["vega"]),
            }
        )
    sections.append("### By Underlying (sorted by |delta|)")
    sections.append(list_table(underlying_rows))

    return "\n".join(sections)
