---
description: Run the biweekly trading review — portfolio health, options, pipeline, macro, retro
---

Execute the structured biweekly trading review. Work through each section in order, running all tool calls and presenting results before moving to the next section.

## 0. PENDING DECISIONS

Call `decision_list` to review all PENDING decisions from prior briefings/reviews. For each:
- Is it still relevant? (position may have been closed or assigned)
- Past deadline? Flag as overdue.
- Completed but not recorded? Close via `decision_close` with outcome.

Present as carry-forward items before starting any analysis.

## 1. MACRO & THESIS CHECK

1. Call `get_market_regime` — verdict + all dimensions (Vol/Trend/Breadth/Macro/Sectors/Credit/Tape/Sentiment/Positioning/Policy) + ⚠ flags. Also call `get_cot_extremes` for crowded positioning across SPX/NDX/VIX/10Y/Gold/WTI, and `get_naaim_history` for the active-manager exposure gauge (52w z-score, percentile, 8-week trend, multi-window context). NAAIM pairs with CFTC COT and the AAII/CBOE p/c readings inside the regime Sentiment dimension — together they triangulate crowding (extreme long → bearish-forward; extreme defensive → squeeze setup). If FOMC within 4 weeks, call `get_prediction_market` for what's priced.

2. **Valuation regime.** Call `get_equity_risk_premium` and `get_yield_curve_state` in parallel — the two reads of how risk-free rates translate into equity multiples. Read in this order:
   - **ERP tier** (Generous / Fair / Tight / Compressed / Compressed-Negative): tells you whether multiples have room to expand or returns will come from earnings only. The historical-P/E decomposition rows (implied ERP at 5y / 10y / quarter-end P/E with current DGS10) say where compression is coming from — multiples vs rates. Compression from multiples is the most fragile; it unwinds with sentiment shifts, not just rate moves.
   - **Curve regime** (Bear/Bull × Steepener/Flattener): the leading-tenor diagnostic over 4w tells you *what* is repricing. Bear Steepener (long end leading) is term-premium / inflation / supply — mechanical multiple compression on long-duration names. Bear Flattener (short end leading) is Fed-path repricing — less hostile to duration but tightens financial conditions. Don't conflate the two; same yield rise, very different implications.
   - **Strategy-weighting feed** — Compressed or below ERP downshifts conviction on high-multiple names (cap accumulate at moderate, prefer CSP over direct buy); Compressed-Negative routes new accumulate to skip. Curve regime shifts strategy weights per the table in [valuation-regime.md](../../docs/valuation-regime.md). Use these to gate Section 2 (oversized name sizing) and Section 5 (new pipeline entries).
   - **Cross-reference** with item 1's Macro dimension (T10Y2Y) and item 10's forward P/E (same FactSet data feeds the ERP tool — the cache means no duplicate fetch). When the un-inversion trap (item 1) AND a Bear Steepener regime fire simultaneously: maximum-defensive posture, both items pointing the same direction.

2a. **Bear regime score — composite synthesis.** Call `get_bear_regime_score`. This is the composite read across the 9 dimensions covered by items 1-2 (curve, ERP, credit, positioning, sentiment, vol, technicals, breadth, dealer flow) — the single 0-10 decision checkpoint. Surface tier + score + the firing dimensions (top contributors).

   **Trajectory matters more than absolute.** Compare to the score from the last review (track via decisions or by noting in retro):
   - Rising tier (Watchful → Building → Defensive over 2-4 weeks) = late-cycle deterioration confirming; act per playbook even if not at Crisis yet
   - Falling tier (Defensive → Building → Watchful) = stress easing; recover normal accumulation cadence per pipeline
   - Flat tier across 2+ reviews = composite is stable; no escalation needed

   **At tier ≥ Building, run the full position-level action review** per [bear-regime-playbook.md](../../docs/bear-regime-playbook.md). For each position from Section 2:
   - Building+: pause-new-accumulation list (P/S >12 OR PEG >3 cohort)
   - Defensive+: trim list (high-multiple cohort + >30% from cost) + tail hedge upsize
   - Crisis: freeze-all-new + reduce-gross plan

   Cross-reference firing dimensions with the dimensional reads from items 1-2 (regime/ERP/curve) — verify they agree before acting. A Building score driven entirely by Positioning + Sentiment (both contrarian indicators that can stay extreme for months) is weaker evidence than one driven by Credit + Breadth + Curve. **Override conditions** in the playbook ("When to override" section) — single-dimension flicker, active macro overhang in memory, recent whipsaw.

2b. **Private-credit channel check (leading indicator, manual — no MCP tool).** The bear-regime Credit dimension above is keyed on **public** HY OAS (`BAMLH0A0HYM2`), which lags. Private-credit / BDC redemption flows run *ahead* of it — the corner where AI-buildout and levered-SaaS stress shows up first because it's marked-to-model. This is the debt-channel sibling of the AI external-funding phase. Three reads, all manual research (private data — Stanger & Co., Barclays/Morningstar BDC notes, WSJ):
   - **Redemption trajectory** — are quarterly redemption requests across the big nontraded BDCs / interval funds (Blackstone, BlackRock, Apollo, Ares, Blue Owl, Oaktree) accelerating or slowing vs prior quarter? Any large fund approaching or hitting its 5% quarterly gate?
   - **New BDC sales** — is the marginal buyer back, or still collapsing? (April 2026 baseline: $1.6B, −74% YoY, lowest since May 2023.)
   - **HY OAS confirmation** — re-pull `get_economic_data BAMLH0A0HYM2` and check whether public spreads have started to widen toward the private stress, or remain at cycle tights (the gap is the signal).

   **Escalation rule:** this is a *watch*, not a trigger, as long as HY OAS stays tight. Escalate to action only when the leading-indicator chain reaches a **gating event AND HY OAS starts widening** — that's the convergence of the leading and lagging reads. When two+ of {redemption acceleration, new-sales collapse, software-loan-loss headlines} inflect together, shift [[project_late_cycle_posture]] from "pre-position" to "act" before HY OAS confirms. See [[project_private_credit_redemptions]] for the full 6-step chain and its links to [[project_ai_capex_funding_phase]] / [[project_circular_financing_buckets]].

2c. **Single-stock ETF froth gauge — leverage + income (quarterly, manual — no MCP tool).** Retail-speculation tell on the "don't get caught" side of the late-cycle posture — sibling of the AI speculative-tier distribution and bear-mocking signals. Two wrappers selling the SAME speculative exposure (MSTR/NVDA/COIN/TSLA): **leveraged** ETFs and **option-income** ETFs. **Cadence: only re-pull once per quarter** (slow-moving structural gauge — skip on reviews where it was checked <~3 months ago; note "last pulled <date>" and move on). When due, web-pull and compare to the baselines in [[project_leveraged_etf_froth]]:
   - **Leverage leg — single-stock ETF count** from ETFdb's single-stock theme list (etfdb.com/themes/single-stock-etfs/). Baseline: ~377 by Dec 2025 (276 launched in 2025 alone).
   - **Leverage leg — total leveraged-product AUM** from industry reports (CNBC / Tidal / InvestmentNews). Baseline: ~$160.5B late-Nov 2025, up ~9x YoY.
   - **Income leg — YieldMax complex AUM + flagship MSTY return-of-capital %.** Baseline: MSTY 65.75% distribution rate but **96.87% return of capital** (30-day SEC yield just 1.50%) — RoC near 100% means the "yield" is pure NAV erosion. The RoC % is the cleanest income-illusion thermometer; rising RoC across the complex = froth deepening.
   - **Read:** trend direction is the whole signal — accelerating count/AUM + concentration in the most-speculative tickers + RoC pinned near 100% = froth deepening. This is a **sizing/timing constraint, NOT a trigger** — froth can run for quarters and a rising count doesn't date the top. HY OAS (item 2b) stays the actual switch. Note the numbers in retro so the trend is reconstructable across quarters.

3. **Recent macro prints (last 14 days).** The five prints with dedicated texture tools are **NFP**, **CPI**, **PCE**, **GDP**, and **FOMC Decision**. Use today's date and known release schedules to determine which are fresh, then call the appropriate texture tool for each:

   - **NFP** (first Friday of each month): `get_jobs_report_texture` — headline + industry mix + U-6/participation/hours/household-vs-establishment divergence + BLS narrative including revisions.
   - **CPI** (~12th of each month): `get_cpi_report_texture` — headline + core + shelter/services/goods/supercore + subcategory detail + tape reaction.
   - **PCE** (~last Friday of each month): `get_pce_report_texture` — headline + core + true supercore + spending/income texture (income, DPI, savings rate) + BEA narrative.
   - **GDP** (advance ~last week of Jan/Apr/Jul/Oct; second + third estimates follow): `get_gdp_report_texture` — headline + composition (PCE/investment/inventory swing/net exports/government pp contributions) + BEA narrative. The inventory and net-trade contributions are the most common sources of headline-misleading prints — eyeball those before the headline.
   - **FOMC Decision**: `get_fomc_decision_texture` — actual decision + statement language delta vs prior. (Prediction-market pricing for the *next* FOMC is already covered in item 1 above.)

   Retrospective read for each: what was the headline vs consensus, what was the tape reaction, and does it shift any active thesis? Surface divergences (headline vs underneath, revisions to prior months, two surveys disagreeing) — do not pre-bake interpretation. If no major print dropped in the past 14 days, skip this item.

4. **Beige Book read.** Call `get_beige_book` (defaults to latest release). Surface period label + which Reserve Bank prepared it + cutoff date. Read the National Summary (Overall Activity / Labor Markets / Prices) and scan the 12 district highlights for divergence (e.g. Dallas energy strength vs San Francisco tech contraction). The Beige Book publishes 8x/year ~2 weeks before each FOMC — so the same release usually carries across 1-2 biweekly reviews. **Two checks:**
   - **New release since last review?** If so, call `get_beige_book release=prior` and explicitly read the language delta. Fed staff make small but deliberate shifts ("modest growth" → "slight" → "flat" → "declining"). A tone shift in the National Summary often pre-prints the next FOMC's stance.
   - **Same release as last review?** Skip the prior-release call. The Beige Book is qualitative context — re-reading the same paragraphs adds no new information. Note period token + move on.

5. **Treasury QRA read (release windows only).** The Quarterly Refunding Announcement publishes 4x/year — Wednesday 8:30 AM in early Feb / May / Aug / Nov. Same cadence-vs-review math as the Beige Book: most biweekly reviews will land on a stale QRA. **Two checks:**
   - **New QRA since last review?** Call `get_qra_texture`. The tool returns latest + prior Policy Statements in one call so language deltas are inspectable. Read in this order:
     - **Auction sizes table** — bill-vs-coupon mix shift is the trade. Coupon increases absorb duration on dealer balance sheets and pressure the long end (Aug 2023 canonical); bill-skew releases duration and supports risk assets (Yellen 2023-24 canonical).
     - **Forward guidance language** — diff "anticipates maintaining auction sizes for at least the next several quarters" (status quo) vs "anticipates increasing" (duration absorption ahead). The phrase change is more important than the size change in any single quarter.
     - **Buyback program updates** — frequency, size, and curve focus (off-the-run liquidity buybacks vs cash-management buybacks have different signaling).
     - **TIPS issuance** — separate paragraph; relevant only if you're trading the breakeven complex.
   - Cross-reference the yield curve table the tool prints (DTB3/DGS2/5/10/30/T10Y2Y) with any rate-sensitive positions. A QRA-day move >5bp at the long end vs a flat front is the typical "duration repricing" tell.
   - **Same QRA as last review?** Skip the call. The statement is immutable and the texture-tool output adds nothing new mid-quarter. Note next QRA date + move on.

6. **Container freight signals — geopolitical-risk confirmation (conditional).** Only call `get_freight_signals` when an active maritime headline is in play (Red Sea / Houthi / Bab el-Mandeb, Strait of Hormuz / Iran tensions, Panama Canal drought, Bosporus / Black Sea, Suez incident). The chokepoint deviation table is mostly noise when nothing is happening — skip the call to avoid context bloat. **When you do call it, read in this order:**
   - **Most-stressed chokepoint headline.** If |Δ%| ≥ 25% on the chokepoint matching the active headline, the rerouting is real (not just news cycle). If headline is loud but chokepoint Δ is small, the disruption is rhetorical, not physical — fade the panic.
   - **Confirming triplet for a Red Sea event:** Suez/Bab el-Mandeb collapsing + Cape of Good Hope surging + FBX13 China-Med + FBX11 China-N Europe spiking 1w/4w. All three required to call it confirmed; any one in isolation is noise.
   - **FBX 1w/4w/8w deltas.** Sustained 4w spike on Suez-routed lanes (FBX03/11/13) is the price-confirmation; cross-reference 8w to distinguish genuine regime shift from short-cover squeeze.
   - **Trade implications:** confirmed disruption = bullish XRT/retailer margin pressure (10-14 day reroute eats into Q-end inventory), bullish ZIM/MATX (rate spike = revenue), bearish goods-CPI deceleration narrative. Note in retro whether positioned trades validated.

7. **DIX/GEX overlay (experimental).** Call `get_dix_gex` — surfaces dark-pool accumulation (DIX) + dealer gamma posture (GEX) with the 2x2 regime cell, divergence flag (10-day SPX vs DIX), 10-day micro trend, and 1m/3m/6m/1y percentile context. Treat as texture, not a verdict — overlay onto the regime call:
   - **Divergence flag present?** This is the highest-signal pattern (distribution into strength or accumulation into weakness). Cross-reference with `get_market_regime` Tape/Sentiment dimensions.
   - **Regime cell** informs structure preferences for the next 2 weeks: DIX-high/GEX-positive favors CSPs+IC; DIX-low/GEX-negative favors hedges over new long-delta. Use this to gate CC writing aggressiveness and CSP strike distance.
   - Note in retro whether the cell call matched the next 2 weeks of price action — track utility over a few cycles before deciding to keep or drop.

8. **TSMC monthly revenue.** Call `get_tsmc_monthly_revenue months=13`. TSMC publishes consolidated monthly revenue around the 10th of each month — a clean leading indicator for the global semi cycle (NVDA / AMD / AVGO / MRVL / ASML / AMAT all foundry-downstream). Biweekly cadence usually catches a fresh print between cycles. Read in this order:
   - **Freshness line** — if `⏰ awaiting print` (latest row older than prior calendar month), note that and continue; the tool still surfaces the prior 12 months' trajectory.
   - **Latest YoY + MoM** — surprise vs the prior 3-month run-rate is the signal. Positive YoY surprise ahead of NVDA / AMD reports is bullish for the semi tape; YoY decel >5pp is a warning for short-dated long-semi exposure.
   - **12-month trajectory** — phase pattern (acceleration vs roll-over) matters more than any single print. Cross-check against the active semi cycle thesis in memory (Phase 1c / Phase 3 timing).
   - Cross-reference any active semi positions and pipeline names from Section 2 / Section 5. This is the single highest-frequency leading indicator we have for that sleeve and should explicitly inform item 12's semi-cycle assessment.

8a. **DRAM spot price check (manual — no MCP tool; while memory exposure is held).** The earliest leading indicator for the memory-cycle turn: spot leads contract prices by 1–2 quarters and leads reported earnings by 2–3. Directly gates trigger **T2** of the MU exit ladder (`~/Documents/analysis/MU/mu_exit_ladder_2026-07-06.md`). TSMC revenue (item 8) is foundry/logic and will NOT catch a memory rollover — this is the memory-side sibling. Web-pull DRAMeXchange/TrendForce spot commentary (no free API):
   - **Spot vs contract direction** — the canonical rollover is spot *declining* while contract still rises. Both rising = cycle intact; both falling = you're late.
   - **Sustained means 2+ weeks**, not a single-day wobble. Cross-check NAND alongside DRAM (NAND typically cracks first — more elastic demand).
   - **Escalation:** first sustained spot rollover → execute MU exit ladder T2 (exit to residual tranche) regardless of headline strength. Note the reading in retro each review so the trend is reconstructable.
   - **Three-major P/B band check (active once SK Hynix's Nasdaq listing trades — debut 2026-07-10).** Valuation altitude gauge — tells you *distribution posture*, never the turn date (P/B reached the peak zone quarters before the price top in prior cycles; the spot/flow signals above are the timing reads). Pull P/B for all three memory majors:
     - **MU** — `get_basic_financials MU`. Historical band ~0.8x (trough) to ~2.5–3x (peak; 2018/2021 tops). Baseline 2026-07-06: **2.52 — in the peak zone** (ROE 70.55).
     - **SK Hynix** — `get_basic_financials SKHY` (Nasdaq listing, debuted 2026-07-10). Korean-convention band ~1.0–2.0x.
     - **Samsung** — no US listing; manual/web pull (Korean P/B is widely published). Band ~1.0–2.0x.
     - **Read:** one name in its peak zone = stock-specific (HBM mix shift can distort); **all three in their peak zones simultaneously = the industry is at peak valuation** — strongest form of the signal, hardens the exit-ladder posture (no adds, CC-as-exit, drift trims) but does NOT itself fire T2/T3. Caveats: book compounds fast at peak earnings (trailing P/B overstates), and "band should shift up because ROE is higher" = the anchor-break/secular argument in valuation clothes — don't accept it implicitly. Note all three readings in retro.
   - Skip entirely once no memory names remain in the book or pipeline.

9. **EIA Weekly Petroleum Status Report.** Call `get_eia_petroleum`. WPSR publishes Wednesday 10:30 ET — biweekly cadence catches a fresh print every cycle. Highest-frequency read on the US oil/products complex; informs CPI energy, consumer demand destruction, and Fed policy path simultaneously. Read in this order:
   - **Consumer pump** — US regular gasoline $/gal with WoW + YoY. A YoY >25% or a single WoW >$0.20 is the canonical "shows up in next CPI energy line + dents discretionary" signal. Cross-reference with restaurants/airlines/XRT in pipeline (MCD-class Q-end commentary catches it first).
   - **SPR move** — sustained draws (>3 mbbl/wk) at high oil = political response to disruption; sustained refills at low oil = strategic buying. The level is a policy signal, not a market signal.
   - **Crude trade balance** — net imports (imp − exp) WoW. Collapsed exports with steady imports = "US holding barrels at home." Confirms or contradicts the freight tool's chokepoint reading: real Hormuz disruption shows up here as imports falling alongside the chokepoint deviation.
   - **Refinery utilization** — >90% sustained = downstream constrained before crude shows it; <85% sustained = demand destruction or refiner discipline (bearish crack spreads either way).
   - **8-week trend table** — phase pattern matters more than any single print; cross-reference active oil/Iran/Hormuz thesis in memory.
   - **Trade implications:** rising pump = bearish discretionary/airlines/restaurants/XRT, bullish XLE/OIH, bearish duration (energy-led inflation tightens Fed reaction).

10. **FactSet Earnings Insight — earnings season pulse.** Call `get_earnings_season_pulse`. FactSet publishes the Earnings Insight PDF every Friday afternoon ET — biweekly cadence catches one or two fresh prints per cycle. This is the institutional benchmark for "what is earnings season actually saying" — S&P 500 aggregate beat rates, surprise magnitudes, blended growth (current + forward quarters + CY), forward 12M P/E with 5y/10y context, and sector-level revision direction since quarter-end. Read in this order:
   - **Beat rate texture** — % of S&P 500 reported, % beating EPS / revenue with 5y averages. Beat rates running well above the 5y average means analysts entered the season too cautious; well below means earnings are missing the mark broadly.
   - **EPS surprise magnitude** — aggregate surprise % vs 5y avg. A large surprise that isn't being rewarded (cross-reference reaction asymmetry below) is the late-cycle tell.
   - **Blended growth + revision delta** — current YoY growth vs the quarter-end estimate. Big positive revisions during the season = analysts were too pessimistic; big negative = guidance cuts dominating.
   - **Forward quarterly + CY EPS growth** — the most-watched forward number. Decel from current quarter to next is the primary tell for cycle peaking.
   - **Forward 12M P/E** — current vs 5y avg, 10y avg, and quarter-end. Anchors valuation regime. P/E expanding into a forward growth deceleration is multiple-driven — bearish setup.
   - **Reaction asymmetry** — beats vs misses ±2-day stock reaction with 5y baseline. Misses being punished much more than average is the canonical "no margin for error" late-cycle signal — pairs with COT crowded-long and NAAIM stretched-long for a high-confidence "size down new entries" call.
   - **Guidance counts** — positive vs negative EPS guidance for next quarter. Forward sentiment from companies themselves; ratio shift WoW is the signal.
   - **Sector revisions** — which sectors moved blended growth up or down since quarter-end, ranked by magnitude. Identifies where surprise positive (or negative) flows concentrated. Cross-reference with active positions and pipeline names from Section 2 / Section 5.
   - **Trade implications:** beat-and-rewarded sectors with rising forward growth = momentum-friendly for new entries; beat-but-punished broad tape = late-cycle, prefer credit spreads / harvest mode over new long-delta; specific sector with big downward revisions while the index revises up = single-name shorting/avoidance window.

11. Call `get_btc_entry_signals` — present the composite score and recommended DCA rate:
   - 0.25x Strongly Unfavorable
   - 0.5x Unfavorable
   - 1x Mixed
   - 1.5x Favorable
   - 2x Strongly Favorable

12. Assess:
   - Semi cycle thesis: any capex guidance changes? Phase timing still on track?
   - Sector rotation: who's leading, who's lagging?
   - Any macro shifts that affect CC expiry timing or coverage ratios?

## 2. PORTFOLIO HEALTH CHECK (positions across all accounts)

1. Call `get_portfolio_summary` — it spans Webull + Tradier + TastyTrade + Fidelity in one call.

2. For each position, check:
   - **Down >15%**: Run the thesis checkpoint (5 questions from docs/management-rules.md). State pass/fail for each. If any fail → recommend exit.
   - **Up >30%**: Flag for "selling into strength" evaluation. Ask: winning or surviving?
   - **Concentration >15%**: Flag as oversized.
   - **Uncovered equity positions**: Flag candidates for CC overlay (emotional armor).

3. Check total portfolio allocation — any concentration violations?

## 3. OPTION POSITIONS REVIEW

1. Call `get_account_positions` for each account to identify open option positions.

2. For each option position:
   - **CCs approaching strike**: Recommend roll up/out or let assign based on CC intent.
   - **CCs/CSPs at >50% profit**: Recommend buy-back.
   - **Expiring within 14 DTE**: Flag for immediate action (close, roll, or let expire).
   - **CSPs**: Check distance to strike vs current price. Is assignment still desirable?

3. Call `get_iv_metrics` on covered positions to check if IV Rank favors writing new CCs.

4. **Wheel accounts** (Webull Roth + Fidelity HSA):
   - Open CSPs: distance to strike, % profit, buy back at 50%?
   - Held shares (if assigned): write CC? At what strike?
   - Open CCs: approaching strike? Let assign or roll?
   - Chain P&L: running total across all wheel cycles per name.
   - Thesis check: still range-bound? Any catalysts changing the picture?

## 4. HEDGE PROGRAM

Biweekly health check on the structural tail hedge. Per [tail-hedge-playbook.md](../../docs/tail-hedge-playbook.md), do NOT open/close/resize based on regime, vol, or signals — only the three playbook triggers drive action.

Call `get_portfolio_greeks`. For each long SPY/QQQ put, call `get_quote greeks=True` for current delta.

Present a snapshot: contracts, strike % OTM, current put delta, DTE, cost basis, P&L %.

Flag against playbook triggers:
- **DTE ≤ 30** → Trigger 3 (routine roll). Run `/hedge`.
- **Put delta -0.20 to -0.40** → Trigger 1 maintenance roll (down) candidate. Run `/hedge`.
- **Strike >30% OTM AND DTE >45-50** → Trigger 1 maintenance roll (up) candidate — rally drifted the put out of the sweet spot into black-swan-only territory. Run `/hedge`.
- **P&L ≥ +400%** → Trigger 2 (harvest tranche) live. Run `/hedge` immediately.
- **Strike <15% OTM** → Legacy correction-zone; migrate to 25% OTM next maintenance window.
- **No hedge in book** → One-time program-commit decision, not a periodic signal call. Run `/hedge` Step 5.

No triggers + hedge exists → **"Hedge healthy, hold."**

## 5. PIPELINE REVIEW

1. Call `pipeline_list` with status "active" to get all active pipeline names. Also call `pipeline_catalyst_list days_ahead=21` to surface the stored catalysts (with their buy-gate / re-eval conditions) landing in the review window — this reads the `pipeline_catalyst_*` table directly, which the general earnings calendar in item 2 does NOT. Cross-reference: a stored catalyst whose conditions are now met (or whose WAITING entry is ready to activate) is a Section 6 action item.

2. For each pipeline name:
   - Check if conviction has changed — any recent news (`get_company_news`) that shifts thesis?
   - Check earnings proximity — call `get_earnings_calendar` and flag any reporting in next 2 weeks. Reconcile against the stored catalysts from item 1: if the catalyst date and the calendar date disagree, use the later date and note the discrepancy.
   - If actionable (ready for entry), summarize: current intent, last signal check, what's needed to pull the trigger.

3. Prioritize: recommend max 2-3 new entries for the next 2-week period.

## 6. RETRO & ACTION ITEMS

1. Summarize trades executed since last review (use `get_order_history` if needed).

2. Check for framework violations:
   - Any single-tranche entries that should have been scaled?
   - Any entries without full Step 1-4 analysis?
   - Any sells into recovery (survived, not won)?
   - **Bear regime score adherence**: if Section 1 item 2a returned Building+, did the trades executed since last review respect the tier's action template? (E.g., did you open a new position in a high-multiple name during a Defensive tier? Surface as a pattern flag, not a self-flagellation — was the override justified?)

3. Present a final **Action Items** list:
   - Positions to exit or trim
   - CCs/CSPs to roll or close
   - Pipeline names to enter (with specific strategy + parameters)
   - Framework or doc updates needed
   - Items to carry forward to next review
