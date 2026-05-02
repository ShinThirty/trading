"""Option strategy backtesting (TastyTrade)."""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients.endpoints import tastytrade as tt

from trading_mcp.helpers import _tastytrade

mcp = FastMCP("backtest-tools")


@mcp.tool()
async def backtest_strategy(
    ctx: Context,
    symbol: str,
    start_date: str,
    end_date: str,
    legs: list[dict],
    entry_conditions: dict | None = None,
    exit_conditions: dict | None = None,
) -> str:
    """Backtest an option strategy against historical data.

    Runs the strategy repeatedly over the date range and returns win rate,
    P&L, and individual trial results.

    symbol: underlying ticker (e.g. 'ADBE'). ~147 symbols available.
    start_date: backtest start (YYYY-MM-DD). Most symbols available from 2013.
    end_date: backtest end (YYYY-MM-DD).
    legs: list of leg dicts, each with:
      - type: 'equity-option' or 'equity'
      - direction: 'long' or 'short'
      - side: 'call' or 'put' (for options)
      - quantity: 1-10 for options, 1-100 for equity
      - strikeSelection: how to pick the strike:
          'delta' (use delta field, 1-100 where 20 = 0.20 delta)
          'percentageOTM' (use percentageOTM field, e.g. 0.10 for 10% OTM)
      - delta: strike delta (e.g. 20 for 0.20 delta)
      - percentageOTM: pct OTM (e.g. 0.10 for 10%)
      - daysUntilExpiration: target DTE (e.g. 45)
    entry_conditions: dict with:
      - frequency: 'every day', 'on specific days of the week',
          'on exact days to expiration match'
      - maximumActiveTrials: max concurrent positions (e.g. 1)
      - maximumActiveTrialsBehavior: 'don't enter' or 'close oldest'
      - minimumVIX / maximumVIX: VIX range filter
    exit_conditions: dict with:
      - takeProfitPercentage: close at X% profit (e.g. 50)
      - stopLossPercentage: close at X% loss
      - atDaysToExpiration: close at N DTE (e.g. 7)
      - afterDaysInTrade: close after N days

    Example CSP backtest:
      symbol='ADBE', start_date='2024-01-01', end_date='2026-04-01',
      legs=[{'type': 'equity-option', 'direction': 'short', 'side': 'put',
             'quantity': 1, 'strikeSelection': 'delta', 'delta': 20,
             'daysUntilExpiration': 45}],
      entry_conditions={'frequency': 'every day', 'maximumActiveTrials': 1,
                        'maximumActiveTrialsBehavior': "don't enter"},
      exit_conditions={'takeProfitPercentage': 50, 'atDaysToExpiration': 7}

    Note: backtests run asynchronously and may take 1-3 minutes.
    Requires [tastytrade] section in ~/.tradingrc.
    """
    client = _tastytrade(ctx)

    result = await client.post(
        tt.BACKTEST_CREATE,
        tt.BacktestRequest(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            legs=legs,
            entry_conditions=entry_conditions or {},
            exit_conditions=exit_conditions or {},
        ),
    )
    bt_id = result.data.get("id")
    if not bt_id:
        return result.to_output()

    for _ in range(100):
        result = await client.get(tt.BACKTEST_GET, tt.BacktestIdRequest(bt_id))
        if result.data.get("status") == "completed":
            return result.to_output()
        await asyncio.sleep(3)

    return f"Backtest {bt_id} still running. Check back later."
