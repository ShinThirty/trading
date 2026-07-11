"""Multi-account portfolio aggregation and formatting.

Composes Webull/Tradier/TastyTrade/SnapTrade account data (fetched by the MCP
server) into a consolidated cross-account portfolio summary and cluster
concentration. The account/position shapes are provider-neutral AccountSummary
objects; provider-specific fetching lives in trading-mcp.
"""

from dataclasses import dataclass, field

from trading_clients.table_helpers import fmt_number, list_table

CASH_EQUIVALENTS = {"FDRXX", "SGOV"}


@dataclass
class NormalizedPosition:
    """One position in the provider-neutral shape the aggregation consumes.

    Every broker's ``to_normalized()`` emits these, so downstream code (summary
    tables, cluster concentration, CSP collateral, greeks) never branches on the
    provider. Equity and cash rows leave the option-only fields at their defaults
    (``is_option`` stays False).

    Mutable by design: the Tradier fetch layer fills ``last``/``value``/``pnl``
    from a batched quote after construction, because Tradier positions arrive
    without a price.
    """

    symbol: str
    quantity: float
    last: float = 0.0
    cost: float = 0.0  # per-share average cost
    value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    is_option: bool = False
    is_cash: bool = False
    # Option-only — unset for equity/cash rows.
    underlying: str = ""
    option_type: str = ""  # "call" | "put" | ""
    strike: float = 0.0
    expiration: str | None = None
    strategy: str = ""
    # Tradier-only: signed total cost basis (positive even for shorts) so the
    # fetch layer can compute sign-correct P&L; other providers leave it 0.0.
    cost_basis: float = 0.0


@dataclass
class AccountSummary:
    account_id: str
    label: str
    broker: str  # "Webull", "Tradier", "TastyTrade", "Fidelity" (via SnapTrade)
    account_type: str  # "CASH", "MARGIN", etc.
    nlv: float = 0.0
    cash: float = 0.0
    market_value: float = 0.0
    day_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    positions: list[NormalizedPosition] = field(default_factory=list)


@dataclass
class PortfolioSummary:
    accounts: list[AccountSummary]
    errors: dict[str, str] = field(default_factory=dict)


def compact_portfolio_summary(summary: PortfolioSummary, file_path: str) -> str:
    """Return a brief summary line with a pointer to the full details file."""
    total_nlv = sum(a.nlv for a in summary.accounts)
    total_day = sum(a.day_pnl for a in summary.accounts)
    n_accounts = len(summary.accounts)
    n_options = sum(1 for a in summary.accounts for p in a.positions if p.is_option)
    n_equity = sum(
        1 for a in summary.accounts for p in a.positions if not p.is_option and not p.is_cash
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
            if not p.is_option:
                continue
            row: dict[str, str] = {
                "Account": a.label,
                "Symbol": p.underlying or p.symbol,
                "Type": p.option_type[0:1].upper(),
                "Strike": fmt_number(p.strike),
                "Exp": p.expiration or "",
                "Qty": fmt_number(p.quantity, 0),
                "Cost": fmt_number(p.cost),
                "Last": fmt_number(p.last),
                "P&L": fmt_number(p.pnl),
                "P&L %": fmt_number(p.pnl_pct),
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
            if p.is_option or p.is_cash:
                continue
            equity_rows.append(
                {
                    "Account": a.label,
                    "Symbol": p.symbol,
                    "Qty": fmt_number(p.quantity, 0),
                    "Cost": fmt_number(p.cost),
                    "Last": fmt_number(p.last),
                    "Mkt Val": fmt_number(p.value),
                    "P&L": fmt_number(p.pnl),
                    "P&L %": fmt_number(p.pnl_pct),
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


@dataclass
class ClusterMember:
    """One cluster ticker's long exposure across all accounts."""

    ticker: str
    equity_value: float = 0.0
    long_option_value: float = 0.0

    @property
    def total(self) -> float:
        return self.equity_value + self.long_option_value


@dataclass
class ClusterConcentration:
    """A correlated cluster's aggregate long exposure vs a target cap."""

    tickers: list[str]
    cap_pct: float
    total_nlv: float
    members: list[ClusterMember]
    unmatched: list[str]

    @property
    def cluster_value(self) -> float:
        return sum(m.total for m in self.members)

    @property
    def cluster_pct(self) -> float:
        return (self.cluster_value / self.total_nlv * 100.0) if self.total_nlv else 0.0

    @property
    def cap_value(self) -> float:
        return self.total_nlv * self.cap_pct / 100.0

    @property
    def overage(self) -> float:
        """Positive = over the cap (trim this much); negative = headroom."""
        return self.cluster_value - self.cap_value


def compute_cluster_concentration(
    accounts: list[AccountSummary], tickers: list[str], cap_pct: float
) -> ClusterConcentration:
    """Aggregate a cluster's long exposure as a share of total book NLV.

    Cluster value = long equity market value + long option market value
    (capital at risk) summed across all accounts for the given tickers.
    Short options (negative quantity — CSPs/CCs) are excluded: they are
    cash-secured premium, not deployed long exposure. Cash rows are ignored.
    """
    wanted = [t.strip().upper() for t in tickers if t.strip()]
    wanted_set = set(wanted)
    equity = dict.fromkeys(wanted, 0.0)
    long_opt = dict.fromkeys(wanted, 0.0)

    for acct in accounts:
        for p in acct.positions:
            if p.is_cash:
                continue
            if p.is_option:
                underlying = (p.underlying or p.symbol).upper()
                if underlying in wanted_set and p.quantity > 0:
                    long_opt[underlying] += p.value
            else:
                sym = p.symbol.upper()
                if sym in wanted_set:
                    equity[sym] += p.value

    total_nlv = sum(a.nlv for a in accounts)
    members: list[ClusterMember] = []
    unmatched: list[str] = []
    for t in wanted:
        if equity[t] == 0.0 and long_opt[t] == 0.0:
            unmatched.append(t)
        else:
            members.append(ClusterMember(t, equity[t], long_opt[t]))
    members.sort(key=lambda m: m.total, reverse=True)
    return ClusterConcentration(wanted, cap_pct, total_nlv, members, unmatched)


def format_cluster_concentration(cc: ClusterConcentration) -> str:
    """Format a cluster-concentration read as markdown."""
    status = "OVER by" if cc.overage > 0 else "under cap by"
    sections = [
        "## Cluster Concentration",
        "",
        f"**Cap {fmt_number(cc.cap_pct, 1)}% of book** — cluster ${fmt_number(cc.cluster_value)}"
        f" = {fmt_number(cc.cluster_pct, 1)}% of ${fmt_number(cc.total_nlv)} NLV",
        f"Cap value ${fmt_number(cc.cap_value)} → **{status} ${fmt_number(abs(cc.overage))}**",
        "",
    ]

    rows: list[dict[str, str]] = []
    for m in cc.members:
        pct = (m.total / cc.total_nlv * 100.0) if cc.total_nlv else 0.0
        rows.append(
            {
                "Ticker": m.ticker,
                "Equity": fmt_number(m.equity_value),
                "Long Opt": fmt_number(m.long_option_value),
                "Total": fmt_number(m.total),
                "% Book": fmt_number(pct, 1),
            }
        )
    sections.append(list_table(rows))

    if cc.unmatched:
        sections.append("")
        sections.append(f"_No long position found for: {', '.join(cc.unmatched)}_")

    sections.append("")
    sections.append(
        "_Cluster value = long equity market value + long option market value (capital at"
        " risk). Short options (CSPs/CCs) are excluded — cash-secured premium, not deployed"
        " long exposure._"
    )
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
