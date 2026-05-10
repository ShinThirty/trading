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

5. **Wheel accounts** (Webull Roth + Fidelity HSA):
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

1. Call `get_market_regime` — verdict + all dimensions (Vol/Trend/Breadth/Macro/Sectors/Credit/Tape/Sentiment/Positioning/Policy) + ⚠ flags. Also call `get_cot_extremes` for crowded positioning across SPX/NDX/VIX/10Y/Gold/WTI, and `get_naaim_history` for the active-manager exposure gauge (52w z-score, percentile, 8-week trend, multi-window context). NAAIM pairs with CFTC COT and the AAII/CBOE p/c readings inside the regime Sentiment dimension — together they triangulate crowding (extreme long → bearish-forward; extreme defensive → squeeze setup). If FOMC within 4 weeks, call `get_prediction_market` for what's priced.

2. **Beige Book read.** Call `get_beige_book` (defaults to latest release). Surface period label + which Reserve Bank prepared it + cutoff date. Read the National Summary (Overall Activity / Labor Markets / Prices) and scan the 12 district highlights for divergence (e.g. Dallas energy strength vs San Francisco tech contraction). The Beige Book publishes 8x/year ~2 weeks before each FOMC — so the same release usually carries across 1-2 biweekly reviews. **Two checks:**
   - **New release since last review?** If so, call `get_beige_book release=prior` and explicitly read the language delta. Fed staff make small but deliberate shifts ("modest growth" → "slight" → "flat" → "declining"). A tone shift in the National Summary often pre-prints the next FOMC's stance.
   - **Same release as last review?** Skip the prior-release call. The Beige Book is qualitative context — re-reading the same paragraphs adds no new information. Note period token + move on.

3. **Treasury QRA read (release windows only).** The Quarterly Refunding Announcement publishes 4x/year — Wednesday 8:30 AM in early Feb / May / Aug / Nov. Same cadence-vs-review math as the Beige Book: most biweekly reviews will land on a stale QRA. **Two checks:**
   - **New QRA since last review?** Call `get_qra_texture`. The tool returns latest + prior Policy Statements in one call so language deltas are inspectable. Read in this order:
     - **Auction sizes table** — bill-vs-coupon mix shift is the trade. Coupon increases absorb duration on dealer balance sheets and pressure the long end (Aug 2023 canonical); bill-skew releases duration and supports risk assets (Yellen 2023-24 canonical).
     - **Forward guidance language** — diff "anticipates maintaining auction sizes for at least the next several quarters" (status quo) vs "anticipates increasing" (duration absorption ahead). The phrase change is more important than the size change in any single quarter.
     - **Buyback program updates** — frequency, size, and curve focus (off-the-run liquidity buybacks vs cash-management buybacks have different signaling).
     - **TIPS issuance** — separate paragraph; relevant only if you're trading the breakeven complex.
   - Cross-reference the yield curve table the tool prints (DTB3/DGS2/5/10/30/T10Y2Y) with any rate-sensitive positions. A QRA-day move >5bp at the long end vs a flat front is the typical "duration repricing" tell.
   - **Same QRA as last review?** Skip the call. The statement is immutable and the texture-tool output adds nothing new mid-quarter. Note next QRA date + move on.

4. **Container freight signals — geopolitical-risk confirmation (conditional).** Only call `get_freight_signals` when an active maritime headline is in play (Red Sea / Houthi / Bab el-Mandeb, Strait of Hormuz / Iran tensions, Panama Canal drought, Bosporus / Black Sea, Suez incident). The chokepoint deviation table is mostly noise when nothing is happening — skip the call to avoid context bloat. **When you do call it, read in this order:**
   - **Most-stressed chokepoint headline.** If |Δ%| ≥ 25% on the chokepoint matching the active headline, the rerouting is real (not just news cycle). If headline is loud but chokepoint Δ is small, the disruption is rhetorical, not physical — fade the panic.
   - **Confirming triplet for a Red Sea event:** Suez/Bab el-Mandeb collapsing + Cape of Good Hope surging + FBX13 China-Med + FBX11 China-N Europe spiking 1w/4w. All three required to call it confirmed; any one in isolation is noise.
   - **FBX 1w/4w/8w deltas.** Sustained 4w spike on Suez-routed lanes (FBX03/11/13) is the price-confirmation; cross-reference 8w to distinguish genuine regime shift from short-cover squeeze.
   - **Trade implications:** confirmed disruption = bullish XRT/retailer margin pressure (10-14 day reroute eats into Q-end inventory), bullish ZIM/MATX (rate spike = revenue), bearish goods-CPI deceleration narrative. Note in retro whether positioned trades validated.

5. **DIX/GEX overlay (experimental).** Call `get_dix_gex` — surfaces dark-pool accumulation (DIX) + dealer gamma posture (GEX) with the 2x2 regime cell, divergence flag (10-day SPX vs DIX), 10-day micro trend, and 1m/3m/6m/1y percentile context. Treat as texture, not a verdict — overlay onto the regime call:
   - **Divergence flag present?** This is the highest-signal pattern (distribution into strength or accumulation into weakness). Cross-reference with `get_market_regime` Tape/Sentiment dimensions.
   - **Regime cell** informs structure preferences for the next 2 weeks: DIX-high/GEX-positive favors CSPs+IC; DIX-low/GEX-negative favors hedges over new long-delta. Use this to gate CC writing aggressiveness and CSP strike distance.
   - Note in retro whether the cell call matched the next 2 weeks of price action — track utility over a few cycles before deciding to keep or drop.

6. **TSMC monthly revenue.** Call `get_tsmc_monthly_revenue months=13`. TSMC publishes consolidated monthly revenue around the 10th of each month — a clean leading indicator for the global semi cycle (NVDA / AMD / AVGO / MRVL / ASML / AMAT all foundry-downstream). Biweekly cadence usually catches a fresh print between cycles. Read in this order:
   - **Freshness line** — if `⏰ awaiting print` (latest row older than prior calendar month), note that and continue; the tool still surfaces the prior 12 months' trajectory.
   - **Latest YoY + MoM** — surprise vs the prior 3-month run-rate is the signal. Positive YoY surprise ahead of NVDA / AMD reports is bullish for the semi tape; YoY decel >5pp is a warning for short-dated long-semi exposure.
   - **12-month trajectory** — phase pattern (acceleration vs roll-over) matters more than any single print. Cross-check against the active semi cycle thesis in memory (Phase 1c / Phase 3 timing).
   - Cross-reference any active semi positions and pipeline names from Section 1 / Section 3. This is the single highest-frequency leading indicator we have for that sleeve and should explicitly inform Step 7's semi-cycle assessment.

7. Call `get_btc_entry_signals` — present the composite score and recommended DCA rate:
   - 0.25x Strongly Unfavorable
   - 0.5x Unfavorable
   - 1x Mixed
   - 1.5x Favorable
   - 2x Strongly Favorable

8. Assess:
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
