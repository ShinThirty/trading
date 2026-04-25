---
description: Run the biweekly trading review — portfolio health, options, pipeline, macro, retro
---

Execute the structured biweekly trading review. Work through each section in order, running all tool calls and presenting results before moving to the next section.

## 1. PORTFOLIO HEALTH CHECK (positions across all accounts)

1. Ask the user if they have fresh Fidelity CSVs to include (exported from Fidelity Positions page to ~/Downloads/fidelity). Call `get_portfolio_summary` with `fidelity_folder` if provided, otherwise Webull-only. Note: Fidelity holds ~$311K across 3 accounts (401k BrokerageLink, blue-chip CSPs, tech CSPs) — without CSVs, the portfolio view is incomplete.

2. For each position, check:
   - **Down >15%**: Run the thesis checkpoint (5 questions from docs/management-rules.md). State pass/fail for each. If any fail → recommend exit.
   - **Up >30%**: Flag for "selling into strength" evaluation. Ask: winning or surviving?
   - **Concentration >15%**: Flag as oversized.
   - **Uncovered equity positions**: Flag candidates for CC overlay (emotional armor).

3. Check total portfolio allocation — any concentration violations?

## 2. OPTION POSITIONS REVIEW

1. Call `decision_list` to review all PENDING decisions from prior briefings/reviews. For each:
   - Is it still relevant? (position may have been closed or assigned)
   - Past deadline? Flag as overdue.
   - Completed but not recorded? Close via `decision_close` with outcome.

2. Call `get_account_positions` for each account to identify open option positions.

3. For each option position:
   - **CCs approaching strike**: Recommend roll up/out or let assign based on CC intent.
   - **CCs/CSPs at >50% profit**: Recommend buy-back.
   - **Expiring within 14 DTE**: Flag for immediate action (close, roll, or let expire).
   - **CSPs**: Check distance to strike vs current price. Is assignment still desirable?

4. Call `get_iv_metrics` on covered positions to check if IV Rank favors writing new CCs.

5. **Wheel accounts** (Webull Roth + Fidelity HSA — CCL and any future wheel names):
   - Open CSPs: distance to strike, % profit, buy back at 50%?
   - Held shares (if assigned): write CC? At what strike?
   - Open CCs: approaching strike? Let assign or roll?
   - Chain P&L: running total across all wheel cycles per name.
   - Thesis check: still range-bound? Any catalysts changing the picture?

## 3. PIPELINE REVIEW

1. Call `pipeline_list` with status "active" to get all active pipeline names.

2. For each pipeline name:
   - Check if conviction has changed — any recent news (`get_company_news`) that shifts thesis?
   - Check earnings proximity — call `get_earnings_calendar` and flag any reporting in next 2 weeks.
   - If actionable (ready for entry), summarize: current intent, last signal check, what's needed to pull the trigger.

3. Prioritize: recommend max 2-3 new entries for the next 2-week period.

## 4. MACRO & THESIS CHECK

1. Call `get_market_regime` — present all four dimensions (volatility, trend, macro, sectors).

2. Call `get_btc_entry_signals` — present the composite score and recommended DCA rate:
   - 0.25x Strongly Unfavorable
   - 0.5x Unfavorable
   - 1x Mixed
   - 1.5x Favorable
   - 2x Strongly Favorable

3. Assess:
   - Semi cycle thesis: any capex guidance changes? Phase timing still on track?
   - Sector rotation: who's leading, who's lagging?
   - Any macro shifts that affect CC expiry timing or coverage ratios?

## 5. RETRO & ACTION ITEMS

1. Summarize trades executed since last review (use `get_order_history` if needed).

2. Check for framework violations:
   - Any single-tranche entries that should have been scaled?
   - Any entries without full Step 1-4 analysis?
   - Any sells into recovery (survived, not won)?

3. Present a final **Action Items** list:
   - Positions to exit or trim
   - CCs/CSPs to roll or close
   - Pipeline names to enter (with specific strategy + parameters)
   - Framework or doc updates needed
   - Items to carry forward to next review
