"""Cluster-concentration aggregation: long exposure of a correlated cluster vs a cap.

compute_cluster_concentration sums long equity + long option market value (capital
at risk) for the named tickers across all accounts, excludes short options
(cash-secured premium, not deployed long exposure), and measures the total against
a cap expressed as a percent of total book NLV.
"""

from trading_clients.portfolio import (
    AccountSummary,
    NormalizedPosition,
    compute_cluster_concentration,
)


def _book() -> list[AccountSummary]:
    """A two-account book: cluster names, a non-cluster name, cash, and options."""
    a = AccountSummary(
        account_id="1",
        label="Cash",
        broker="Webull",
        account_type="CASH",
        nlv=800_000.0,
        positions=[
            NormalizedPosition(symbol="META", quantity=300, value=200_000.0),
            NormalizedPosition(symbol="MU", quantity=250, value=220_000.0),
            # non-cluster name — must be ignored
            NormalizedPosition(symbol="NFLX", quantity=500, value=44_000.0),
            # long call on a cluster name — counted at premium (capital at risk)
            NormalizedPosition(
                symbol="NVDA260115C00150000",
                underlying="NVDA",
                value=11_000.0,
                quantity=2,
                is_option=True,
            ),
            # short put on a cluster name — must be EXCLUDED (negative qty)
            NormalizedPosition(
                symbol="MU260717P00900000",
                underlying="MU",
                value=-6_800.0,
                quantity=-2,
                is_option=True,
            ),
            NormalizedPosition(symbol="FDRXX", quantity=100_000, value=100_000.0, is_cash=True),
        ],
    )
    b = AccountSummary(
        account_id="2",
        label="Roth",
        broker="Webull",
        account_type="CASH",
        nlv=200_000.0,
        positions=[
            # same cluster ticker in a second account — must aggregate
            NormalizedPosition(symbol="META", quantity=30, value=20_000.0),
        ],
    )
    return [a, b]


def test_cluster_aggregates_long_equity_and_long_options_across_accounts():
    cc = compute_cluster_concentration(_book(), ["META", "MU", "NVDA", "AVGO"], cap_pct=35.0)

    # META aggregates across both accounts; MU short put excluded; NVDA long call at premium.
    by_ticker = {m.ticker: m for m in cc.members}
    assert by_ticker["META"].total == 220_000.0  # 200k + 20k
    assert by_ticker["MU"].total == 220_000.0  # equity only — short put excluded
    assert by_ticker["MU"].long_option_value == 0.0
    assert by_ticker["NVDA"].total == 11_000.0  # long call premium

    # AVGO has no position — reported as unmatched, not a zero row.
    assert cc.unmatched == ["AVGO"]
    assert "AVGO" not in by_ticker

    # Cluster total = 220k + 220k + 11k = 451k over a 1.0M book.
    assert cc.total_nlv == 1_000_000.0
    assert cc.cluster_value == 451_000.0
    assert cc.cluster_pct == 45.1
    assert cc.cap_value == 350_000.0
    assert cc.overage == 101_000.0  # positive → over cap by this much


def test_under_cap_reports_negative_overage():
    cc = compute_cluster_concentration(_book(), ["NVDA"], cap_pct=35.0)
    assert cc.cluster_value == 11_000.0
    assert cc.overage < 0  # headroom, not a trim


def test_members_sorted_by_total_descending():
    cc = compute_cluster_concentration(_book(), ["NVDA", "MU", "META"], cap_pct=35.0)
    totals = [m.total for m in cc.members]
    assert totals == sorted(totals, reverse=True)
