---
description: Daily market briefing — regime, position alerts, pipeline catalysts
---

Quick daily check-in. Regime context + actionable items from live positions and pipeline. Keep it tight — this is not the biweekly review.

## Step 0: Pending Decisions

Call `decision_list` to check for any PENDING decisions from prior briefings or reviews. Present them as carry-forward items — note any past deadlines. These feed into Step 4's action items.

## Step 1: Market Regime

Call `get_market_regime`. Present the 5 regime labels (volatility, trend, breadth, macro, sectors) in a single row table. Below the table, note any regime shifts that affect strategy preferences (e.g., "Elevated vol = widen CSP strikes" or "Risk-Off = hedge window").

### Commodity Divergence Check

Also call `get_quote USO,USL,BNO,VIX` and `get_tradier_history USO` (last 10 days). Check:

1. **Equity vol divergence**: USO 5-day % change vs VIX 5-day point change
   - If USO up >5% over 5+ sessions while VIX stays sub-20 and SPY holds within 1% of ATH → flag as **🔴 Commodity divergence firing**
   - Inflationary supply shock not being priced in equity vol. Refer to `/hedge` for full reversal signal scoring.

2. **Backwardation monitor (USO/USL ratio)**: Front-month vs 12-month strip ratio
   - Compute `USO_price / USL_price` — this measures futures curve shape
   - **Rising ratio** = deepening backwardation = physical supply tightness intensifying (front-month rallying faster than back-month)
   - **Falling ratio** = curve normalizing = supply stress easing
   - Track day-over-day: a >5% expansion in one day suggests supply math is breaking faster than political timeline
   - Reference: ratio of ~2.80 on 2026-04-29 with USO at $150.63, USL at $53.84 (active Iran blockade backdrop)

3. **Brent confirmation (BNO)**: Cross-check that this isn't WTI-only
   - If USO rallies but BNO doesn't → US-specific (less concerning)
   - If both rally together → global supply story (more concerning)

If all three flat/easing, note "✅ no divergence, curve normalizing" and skip. If any firing, surface the table briefly. Don't expand unless active.

## Step 2: Position Alerts

1. Ask the user if they have fresh Fidelity CSVs to include (exported from Fidelity Positions page to ~/Downloads/fidelity). Call `get_portfolio_summary` with `fidelity_folder` if provided, otherwise Webull-only.

2. Scan for positions needing attention TODAY or within the next 7 days:
   - **Options expiring within 14 DTE**: flag for roll/close/let-expire decision
   - **Options at >50% profit**: flag for early close
   - **Short options approaching strike** (ITM or <3% OTM): flag for roll or assignment prep
   - **Positions down >15%**: one-line thesis check — still valid or deteriorating?
   - **Positions up >30%**: flag for trim/CC overlay consideration

3. Call `roll_list` with status "PLANNED" or "WORKING" to check pending rolls.

4. Call `get_iv_metrics` on any underlying with expiring or approaching-strike options to check IV environment for roll timing.

Skip positions with no alerts. Only surface what needs action.

## Step 2b: Hedge Monitor

Check portfolio-level hedge health. Call `get_portfolio_greeks` (with `fidelity_folder` if provided in Step 2).

Present a hedge snapshot table:

| Metric | Value |
|--------|-------|
| Net Delta | (total across all positions) |
| Hedge Delta | (delta from long puts only) |
| Hedge Ratio | hedge delta / net delta (before hedge) |
| Net Vega | (exposure to IV changes) |
| Hedge DTE | days to expiration on protective puts |
| Hedge P&L | current mark vs cost |

Flag if any of these conditions are true:
- **Hedge DTE <14**: roll or replace decision needed soon
- **Hedge ratio <10%**: underhedged relative to portfolio delta
- **Net vega < -$2,000**: significant short vol exposure — an IV spike would hurt
- **No hedge positions found**: flag as unhedged

One-liner on whether hedge is adequate given current regime (from Step 1). For example, "Elevated vol + downtrend = hedge is critical" vs "Low vol + uptrend = hedge is optional, consider letting it expire."

## Step 3: Pipeline Catalysts

1. Call `pipeline_list` (active entries only).

2. Call `get_iv_metrics` on all pipeline tickers (comma-separated, one call).

3. Flag entries where:
   - **Earnings within 14 days**: pre-earnings positioning window
   - **IV Rank >50%**: premium-selling window opening
   - **IV Rank <30% + bullish intent**: cheap option buying window
   - **Status is WAITING with conditions now met**: ready to activate

Present a short table: ticker, intent, IV Rank, next catalyst, action needed.

## Step 4: Summary

Present a concise action items list:
- **Urgent** (today): options expiring, rolls due, assignments
- **This week**: approaching positions, pipeline entries ready for entry
- **Watch**: regime shifts, upcoming earnings, IV changes

No more than 10 items total. If nothing is actionable, say so — "all clear" is a valid briefing.

After presenting the summary, offer to record any new action items as decisions via `decision_add` (with source "briefing" and appropriate deadlines). Also offer to close any pending decisions that are now resolved.
