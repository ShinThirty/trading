---
description: Review all pipeline names — flag stale entries, upcoming catalysts, and actionable candidates
---

Scan the full pipeline and surface what needs attention.

## Step 1: Load Pipeline

1. Call `pipeline_list` with status "active" to get all active pipeline entries.
2. Call `pipeline_list` with status "watching" to get watchlist entries.

Present a summary table of all entries grouped by priority/intent.

## Step 2: Catalyst Scan

For each active pipeline name, run these checks in parallel (batch by provider to respect rate limits):

1. Call `get_earnings_calendar` for all pipeline tickers — flag any reporting in the next 4 weeks.
2. Call `get_iv_metrics` for all pipeline tickers — flag IV Rank changes (>50% = sell premium window, <30% = buy premium window).

Present a catalyst timeline sorted by date.

## Step 3: Conviction Check

For any pipeline name where:
- Last update was >30 days ago, OR
- Earnings are within 2 weeks, OR
- IV Rank shifted significantly since last check

Run `get_entry_signals` to refresh conviction and signals. Flag any conviction changes (upgraded, downgraded, or newly negative).

## Step 4: Actionable Candidates

Based on the refresh, identify the top 2-3 names that are ready for entry:
- Conviction is confirmed (not stale)
- Signals align (IV environment matches strategy)
- No blocking circuit breakers
- Capital is available (check against 60% CSP collateral cap and 15% concentration limit)

For each actionable name, present:
- **Intent** and **strategy** (from pipeline entry or refreshed)
- **Specific parameters**: strike target, DTE range, earnings interaction
- **What's needed to pull the trigger**: e.g., "wait for post-earnings" or "ready now"

## Step 5: Housekeeping

Flag pipeline entries that should be:
- **Closed**: thesis broken, position already filled, or no longer interested
- **Demoted to watching**: conviction dropped but not fully abandoned
- **Promoted to active**: watching entry with improved conviction

Present a final action items list.
