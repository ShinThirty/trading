"""Guards against silent loss of MCP tools.

If a function disappears or loses its @mcp.tool() decorator (e.g. swallowed by
an Edit whose old_string boundary crossed a function signature), this test
fails. When intentionally adding/removing a tool, update EXPECTED_TOOLS in the
same change — that explicit one-line edit is the point.
"""

import importlib

# Module path → set of expected MCP tool names registered in that module.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "trading_mcp.tools.account": {
        "get_account_balance",
        "get_account_positions",
        "refresh_webull_token",
        "get_app_subscriptions",
        "get_instruments",
        "get_portfolio_summary",
        "get_csp_utilization",
        "get_free_capital",
        "get_portfolio_greeks",
    },
    "trading_mcp.tools.backtest": {
        "backtest_strategy",
    },
    "trading_mcp.tools.beige_book": {
        "get_beige_book",
    },
    "trading_mcp.tools.calendar": {
        "get_earnings_calendar",
        "get_fmp_earnings_calendar",
        "get_dividend_history",
        "get_upcoming_economic_releases",
    },
    "trading_mcp.tools.cn_market": {
        "get_cn_quote",
        "get_cn_history",
        "get_cn_company_info",
        "get_cn_financials",
        "get_cn_fund_flow",
        "get_cn_stock_connect",
    },
    "trading_mcp.tools.crypto": {
        "get_crypto_quote",
        "get_crypto_history",
        "get_btc_entry_signals",
    },
    "trading_mcp.tools.decisions": {
        "decision_add",
        "decision_list",
        "decision_get",
        "decision_update",
        "decision_close",
    },
    "trading_mcp.tools.earnings": {
        "get_earnings_transcript",
        "get_earnings_release",
    },
    "trading_mcp.tools.freight": {
        "get_freight_signals",
    },
    "trading_mcp.tools.fundamentals": {
        "get_company_profile",
        "get_income_statement",
        "get_balance_sheet",
        "get_cash_flow",
        "get_key_metrics",
        "get_basic_financials",
        "get_eps_estimates",
        "get_recommendation_trends",
        "get_price_target",
        "get_company_peers",
        "get_insider_transactions",
        "get_institutional_ownership",
        "scan_informed_activity",
    },
    "trading_mcp.tools.macro": {
        "get_economic_data",
        "get_fred_series_info",
        "search_fred_series",
        "get_sector_performance",
        "get_jobs_report_texture",
        "get_cpi_report_texture",
        "get_market_regime",
        "get_pce_report_texture",
        "get_gdp_report_texture",
        "get_fomc_decision_texture",
    },
    "trading_mcp.tools.naaim": {
        "get_naaim_history",
    },
    "trading_mcp.tools.news": {
        "get_company_news",
        "get_market_news",
        "get_news_sentiment",
        "search_reddit",
        "get_subreddit_posts",
        "get_reddit_post",
        "get_youtube_transcript",
    },
    "trading_mcp.tools.options": {
        "get_option_expirations",
        "get_option_strikes",
        "get_option_chain",
        "get_option_lookup",
        "get_iv_metrics",
        "get_expected_move",
        "analyze_option_strategy",
        "analyze_roll",
        "compare_credit_efficiency",
        "compare_debit_efficiency",
        "project_option_grid",
        "get_cc_coverage",
        "get_cc_chain_pnl",
    },
    "trading_mcp.tools.orders": {
        "get_open_orders",
        "get_order_history",
        "get_order_detail",
        "preview_order",
        "place_order",
        "replace_order",
        "cancel_order",
    },
    "trading_mcp.tools.pipeline": {
        "pipeline_add",
        "pipeline_update",
        "pipeline_get",
        "pipeline_list",
        "pipeline_note",
        "pipeline_close",
    },
    "trading_mcp.tools.pipeline_catalysts": {
        "pipeline_catalyst_add",
        "pipeline_catalyst_list",
        "pipeline_catalyst_update",
        "pipeline_catalyst_close",
    },
    "trading_mcp.tools.quotes": {
        "get_tradier_history",
        "search_symbols",
        "get_quote",
        "get_timesales",
        "get_vwap",
        "get_market_clock",
        "get_technical_indicators",
    },
    "trading_mcp.tools.rolls": {
        "roll_add",
        "roll_list",
        "roll_get",
        "roll_update",
        "roll_close",
    },
    "trading_mcp.tools.screens": {
        "screen_stocks",
        "get_predefined_screen",
        "get_top_movers",
        "get_short_interest",
        "get_public_watchlists",
        "get_public_watchlist",
        "get_short_volume",
    },
    "trading_mcp.tools.signals": {
        "get_conviction_metrics",
        "calculate_position_size",
        "calculate_hedge",
        "get_entry_signals",
    },
    "trading_mcp.tools.squeeze_metrics": {
        "get_dix_gex",
    },
    "trading_mcp.tools.treasury": {
        "get_qra_texture",
    },
    "trading_mcp.tools.tsmc": {
        "get_tsmc_monthly_revenue",
    },
}


def test_no_tools_were_lost() -> None:
    """Each expected tool must (a) exist as a module attribute and (b) be a
    FastMCP-decorated callable. FastMCP marks decorated functions with the
    `__fastmcp__` attribute — losing the @mcp.tool() decorator clears this."""
    failures: list[str] = []
    for module_path, expected in EXPECTED_TOOLS.items():
        try:
            mod = importlib.import_module(module_path)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{module_path}: import failed — {type(e).__name__}: {e}")
            continue
        for name in sorted(expected):
            obj = getattr(mod, name, None)
            if obj is None:
                failures.append(f"{module_path}.{name} disappeared from module")
                continue
            if not hasattr(obj, "__fastmcp__"):
                failures.append(f"{module_path}.{name} lost its @mcp.tool() decorator")
    assert not failures, "Tool-registration regressions:\n  " + "\n  ".join(failures)
