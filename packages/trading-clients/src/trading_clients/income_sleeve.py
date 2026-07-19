"""Income-sleeve ledger: realized return and drawdown of the harvest-premium CSP
book, measured off the transaction feed and benchmarked against the index.

Account value is polluted by contributions (IRA/Roth/HSA deposits, 401k payroll),
money-market interest, and non-sleeve marks. The transaction ledger is immune:
net premium is the signed cash of the option fills, and collateral is the strike
notional the short puts tie up — neither moves when cash is contributed.

The sleeve's mandate is NOT to beat the index on absolute return (a capped
short-vol book can't), but to **match the index with less drawdown** — so the
ledger reports the sleeve's period return and realized drawdown next to SPY
buy-and-hold over the same window. Pure computation; the MCP tool fetches the
SnapTrade activities, option positions, and SPY history and passes them here.
See docs/income-sleeve.md.
"""

from dataclasses import dataclass
from datetime import date

from trading_clients.table_helpers import fmt_number, kv_table, list_table

# Activity types that are not strategy cash flows — excluding them is what makes
# the yield contribution-immune (SnapTrade tags each of these as its own type).
_SKIP_TYPES = {"CONTRIBUTION", "WITHDRAWAL", "TRANSFER", "DIVIDEND", "INTEREST"}

# Option lifecycle events with no cash impact — premium was booked at open.
_ZERO_CASH_OPTION_TYPES = {"OPTIONEXPIRATION", "OPTIONASSIGNMENT"}

# Money-market sweep tickers (Fidelity core) — cash parking, not a trade.
_CASH_EQUIVALENTS = {"FDRXX", "SPAXX", "FZFXX", "SPRXX"}

_TBILL_FLOOR_PCT = 4.5  # the sweep rate the collateral earns; the absolute floor


def _is_option(act: dict) -> bool:
    return bool((act.get("option_symbol") or {}).get("ticker"))


def _equity_symbol(act: dict) -> str:
    sym = act.get("symbol") or {}
    inner = sym.get("symbol")
    if isinstance(inner, dict):
        return inner.get("symbol") or ""
    return inner or ""


def _is_cash_sweep(act: dict) -> bool:
    if "CORE ACCOUNT" in (act.get("description") or "").upper():
        return True
    return _equity_symbol(act).upper() in _CASH_EQUIVALENTS


def _day_diff(start: str, end: str) -> int:
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except ValueError:
        return 0


def max_drawdown_pct(closes: list[float]) -> float:
    """Worst peak-to-trough decline of a price series, as a negative %.
    0.0 if the series only rises or is too short."""
    peak = float("-inf")
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, (c - peak) / peak * 100.0)
    return worst


@dataclass
class SleeveLedger:
    """Realized harvest ledger over [inception, as_of], contribution-immune."""

    inception: str
    as_of: str
    days: int
    net_option_premium: float  # STO credits − BTC/buyback debits (fees pre-netted)
    gross_credits: float  # sum of positive option cash (opens)
    gross_debits: float  # sum of negative option cash (closes/buybacks) — signed
    fees: float  # informational; already reflected in the amounts
    share_cash_flow: float  # net cash from share legs (assignments/sales), not P&L-matched
    n_option_txns: int
    collateral: float  # current open short-put collateral in the sleeve accounts
    premium_by_account: dict[str, float]
    realized_drawdown: float = 0.0  # worst dip in cumulative option premium (positive $)

    @property
    def floor_pct(self) -> float:
        return _TBILL_FLOOR_PCT

    @property
    def premium_yield_pct(self) -> float | None:
        """Net option premium as an annualized % of current collateral — the
        increment over the cash floor. None until there is collateral and a day."""
        if self.collateral <= 0 or self.days < 1:
            return None
        return self.net_option_premium / self.collateral * (365.0 / self.days) * 100.0

    @property
    def total_yield_pct(self) -> float | None:
        """Annualized premium increment + the sweep rate the collateral earns."""
        py = self.premium_yield_pct
        return None if py is None else py + _TBILL_FLOOR_PCT

    @property
    def period_return_pct(self) -> float | None:
        """Total sleeve return OVER THE WINDOW (not annualized) — premium on
        collateral plus the sweep accrued — for an apples-to-apples index compare."""
        if self.collateral <= 0 or self.days < 1:
            return None
        premium = self.net_option_premium / self.collateral * 100.0
        sweep = _TBILL_FLOOR_PCT * (self.days / 365.0)
        return premium + sweep

    @property
    def realized_drawdown_pct(self) -> float | None:
        """Worst realized cumulative-premium dip as a negative % of collateral."""
        if self.collateral <= 0:
            return None
        return -self.realized_drawdown / self.collateral * 100.0


def compute_sleeve_ledger(
    activities_by_account: dict[str, list[dict]],
    collateral_by_account: dict[str, float],
    inception: str,
    as_of: str,
) -> SleeveLedger:
    """Fold the raw SnapTrade activity rows into a harvest ledger.

    `activities_by_account`: account label → list of raw activity dicts (already
    date-bounded by the API). `collateral_by_account`: label → current short-put
    collateral (strike × 100 × contracts). Both keyed by account label.
    """
    net = credits = debits = fees = share = 0.0
    n_opt = 0
    premium_by_account: dict[str, float] = {}
    dated_premium: list[tuple[str, float]] = []
    for label, acts in activities_by_account.items():
        acct_premium = 0.0
        for act in acts:
            atype = (act.get("type") or "").upper()
            if atype in _SKIP_TYPES or _is_cash_sweep(act):
                continue
            amount = float(act.get("amount") or 0.0)  # signed, already net of fee
            if _is_option(act):
                if atype in _ZERO_CASH_OPTION_TYPES:
                    continue
                net += amount
                acct_premium += amount
                fees += float(act.get("fee") or 0.0)
                n_opt += 1
                dated_premium.append(((act.get("trade_date") or "")[:10], amount))
                if amount >= 0:
                    credits += amount
                else:
                    debits += amount
            else:
                share += amount  # equity leg of a wheel (assigned buy / sale)
        if acct_premium:
            premium_by_account[label] = acct_premium

    # Realized drawdown: worst peak-to-trough dip in cumulative option premium.
    dated_premium.sort(key=lambda x: x[0])
    cum = peak = worst = 0.0
    for _, amt in dated_premium:
        cum += amt
        peak = max(peak, cum)
        worst = max(worst, peak - cum)

    return SleeveLedger(
        inception=inception,
        as_of=as_of,
        days=_day_diff(inception, as_of),
        net_option_premium=net,
        gross_credits=credits,
        gross_debits=debits,
        fees=fees,
        share_cash_flow=share,
        n_option_txns=n_opt,
        collateral=sum(collateral_by_account.values()),
        premium_by_account=premium_by_account,
        realized_drawdown=worst,
    )


def _benchmark_block(
    ledger: SleeveLedger, spy_return_pct: float, spy_maxdd_pct: float
) -> list[str]:
    srp = ledger.period_return_pct
    sdd = ledger.realized_drawdown_pct
    if srp is None or sdd is None:
        return []
    table = list_table(
        [
            {
                "Metric": "Period return",
                "Sleeve": f"{srp:+.1f}%",
                "SPY buy-hold": f"{spy_return_pct:+.1f}%",
            },
            {
                "Metric": "Max drawdown",
                "Sleeve": f"{sdd:.1f}% (realized*)",
                "SPY buy-hold": f"{spy_maxdd_pct:.1f}%",
            },
        ]
    )
    less_dd = abs(sdd) < abs(spy_maxdd_pct)
    gap = srp - spy_return_pct
    verdict = (
        f"**Mandate check:** {'less' if less_dd else 'MORE'} drawdown than SPY; "
        f"return {'ahead of' if gap >= 0 else 'behind'} SPY by {abs(gap):.1f}pp "
        f"(index-like return with less drawdown is the target — return lag in a bull "
        f"window is by design; judge over a full cycle)."
    )
    return [
        "",
        f"### vs S&P 500 (SPY) — {ledger.inception} → {ledger.as_of} "
        f"({ledger.days}d, period returns, not annualized)",
        "",
        table,
        "",
        verdict,
        "",
        "_*realized cash-flow drawdown (option premium only) — understates unrealized "
        "MTM on open puts; true NAV drawdown needs daily marks (v2). SPY return is "
        "price-only (dividends excluded, ~immaterial intra-quarter)._",
    ]


def format_sleeve_ledger(
    ledger: SleeveLedger,
    coverage_note: str,
    *,
    spy_return_pct: float | None = None,
    spy_maxdd_pct: float | None = None,
) -> str:
    if ledger.n_option_txns == 0 and ledger.collateral == 0 and ledger.share_cash_flow == 0:
        return (
            f"## Income Sleeve Ledger\n\n"
            f"Inception {ledger.inception} → {ledger.as_of} ({ledger.days}d). "
            f"No sleeve activity yet — the ledger starts accruing once legs are on.\n\n"
            f"_{coverage_note}_"
        )

    py = ledger.premium_yield_pct
    if py is None:
        yield_line = "n/a (needs open collateral + ≥1 day of history)"
    else:
        yield_line = (
            f"{py:.1f}% premium increment · {ledger.total_yield_pct:.1f}% total "
            f"(incl. ~{ledger.floor_pct:.1f}% sweep) vs {ledger.floor_pct:.1f}% cash floor"
        )

    summary = kv_table(
        {
            "Window": f"{ledger.inception} → {ledger.as_of} ({ledger.days}d)",
            "Net option premium": f"${fmt_number(ledger.net_option_premium)}",
            "  ├ gross credits (opens)": f"${fmt_number(ledger.gross_credits)}",
            "  └ gross debits (buybacks)": f"${fmt_number(ledger.gross_debits)}",
            "Fees (already netted above)": f"${fmt_number(ledger.fees)}",
            "Share cash flow (wheel, unmatched)": f"${fmt_number(ledger.share_cash_flow)}",
            "Option transactions": str(ledger.n_option_txns),
            "Current CSP collateral": f"${fmt_number(ledger.collateral)}",
            "Annualized yield": yield_line,
        }
    )

    sections = [f"## Income Sleeve Ledger\n\n{summary}"]
    if ledger.premium_by_account:
        rows = [
            {"Account": k, "Net Premium": f"${fmt_number(v)}"}
            for k, v in sorted(
                ledger.premium_by_account.items(), key=lambda kv: kv[1], reverse=True
            )
        ]
        sections.append(f"\n### Premium by account\n\n{list_table(rows)}")
    if spy_return_pct is not None and spy_maxdd_pct is not None:
        sections.extend(_benchmark_block(ledger, spy_return_pct, spy_maxdd_pct))
    sections.append(f"\n_{coverage_note}_")
    return "\n".join(sections)
