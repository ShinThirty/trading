---
description: Daily market briefing — regime, position alerts, pipeline catalysts
---

Quick daily check-in. Regime context + actionable items from live positions and pipeline. Keep it tight — this is not the biweekly review.

## Step 0: Pending Decisions

Call `decision_list` to check for any PENDING decisions from prior briefings or reviews. Present them as carry-forward items — note any past deadlines. These feed into Step 4's action items.

## Step 1: Market Regime

Call `get_market_regime`. Surface the verdict + dimensional labels (Volatility, Trend, Breadth, Macro, Sectors, Credit, Tape Speed, Sentiment, Positioning, Policy) and any ⚠ Extended / ⚠ Sentiment flags. Note shifts that affect strategy (e.g., "Crowded Long = fade strength", "Cut Bias priced = benchmark rate-sensitive bets vs consensus").

### Commodity Divergence Check

Also call `get_quote USO,USL,BNO,VIX` and `get_tradier_history USO` (last 10 days). Check:

1. **Equity vol divergence**: USO 5-day % change vs VIX 5-day point change
   - If USO up >5% over 5+ sessions while VIX stays sub-20 and SPY holds within 1% of ATH → flag as **🔴 Commodity divergence firing**
   - Inflationary supply shock not yet priced in equity vol. **Informational only** — adjust position-level strikes/sizing (deeper CSPs, smaller new entries, momentum names sized down). Does NOT drive structural hedge changes; the program is trigger-based, not signal-based (see [tail-hedge-playbook.md](../../docs/tail-hedge-playbook.md)).

2. **Backwardation monitor (USO/USL ratio)**: Front-month vs 12-month strip ratio
   - Compute `USO_price / USL_price` — this measures futures curve shape
   - **Rising ratio** = deepening backwardation = physical supply tightness intensifying (front-month rallying faster than back-month)
   - **Falling ratio** = curve normalizing = supply stress easing
   - Track day-over-day: a >5% expansion in one day suggests supply math is breaking faster than political timeline

3. **Brent confirmation (BNO)**: Cross-check that this isn't WTI-only
   - If USO rallies but BNO doesn't → US-specific (less concerning)
   - If both rally together → global supply story (more concerning)

If all three flat/easing, note "✅ no divergence, curve normalizing" and skip. If any firing, surface the table briefly. Don't expand unless active.

4. **Speculator positioning (only when #1 or #2 is firing)**: Call `get_cot_positioning contract=WTI`. Read the 52w z-score:
   - **Crowded Long** (z > +1.5): late-cycle rally — supply tightness already in price, positioning stretched. Fade strength.
   - **Crowded Short** (z < -1.5): squeeze fuel — physical tightness + short positioning is an explosive setup.
   - **Mixed/Neutral**: divergence is what price says, no positioning amplification.

## Step 1a: Valuation Regime

Call `get_equity_risk_premium` and `get_yield_curve_state` in parallel. Surface in 2 lines:

- **ERP tier**: Generous / Fair / Tight / Compressed / Compressed-Negative + the bps value
- **Curve regime**: Bear Steepener / Bear Flattener / Bull Steepener / Bull Flattener / Quiet / Mixed + leading tenor on 4w basis

Most days these don't shift. Flag explicitly only when either crosses into a more hostile tier vs the prior briefing — **Compressed-Negative ERP** or **Bear Steepener with long end leading** — since both gate strategy weighting downstream. Bear Flattener is *less* hostile than Bear Steepener at the same yield level (Fed-path repricing vs term-premium expansion); don't conflate them.

See [valuation-regime.md](../../docs/valuation-regime.md) for tier-to-strategy mapping. The tiers persist; the numbers don't — re-pull rather than recall.

## Step 1b: Macro Print Reaction (release days only)

Call `get_upcoming_economic_releases`. The five prints with dedicated texture tools — exact `Release` column labels — are **`Employment Situation (NFP)`**, **`CPI`**, **`Personal Income and Outlays (PCE)`**, **`GDP`**, and **`FOMC Decision`**. Only these trigger Step 1b. If today's date matches none of them, **skip this section entirely** (but keep the tool output for Step 4's Watch list).

On a **NFP day**, call `get_jobs_report_texture` — headline + industry mix + underneath (U-6, participation, hours, household-vs-establishment divergence, decimal-precision U-3) + intraday tape + the BLS press release narrative including revisions.

On a **CPI day**, call `get_cpi_report_texture` — headline + core + major components (energy/food/shelter/services/goods/supercore proxy) + subcategory detail (rent, OER, gasoline, used cars, new vehicles, medical, public transportation) + tape (incl TIP for inflation expectations) + BLS press release narrative.

On a **PCE day**, call `get_pce_report_texture` — headline PCE + core + true supercore (services ex housing & energy) + spending/income texture (personal income, DPI, nominal+real PCE, savings rate) + goods/services price split + tape (incl TIP) + BEA press release narrative.

On a **GDP day** (advance / second / third estimate), call `get_gdp_report_texture` — headline (real GDP %chg SAAR + nominal + deflator + final sales to private domestic purchasers as the "core" GDP measure) + composition (pp contributions for PCE / investment / inventory swing / net exports / government, summing to real GDP %chg) + components (real %chg SAAR for PCE, GPDI with residential/nonresidential/equipment, exports, imports, government federal vs state & local) + tape (incl TIP) + BEA press release narrative. The inventory and net-trade contributions are the most common sources of "headline-misleads" GDP prints — eyeball those before the headline.

On a **FOMC day**, call `get_fomc_decision_texture` AND `get_prediction_market source=polymarket key=<next-fomc-event-slug>` in parallel. Texture gives the actual decision + statement language delta; Polymarket gives the full pre-decision outcome distribution (slug surfaced by Step 1's regime Policy dimension). Read the surprise: actual outcome vs what was priced. A 5bp gap between consensus and delivery moves the tape harder than the absolute decision.

Surface the texture data — do NOT pre-bake interpretation. Note the divergences worth flagging (headline vs underneath, two surveys disagreeing, sector quality, revisions to prior months) and let the user make the judgment call together. If the print hasn't dropped yet, flag: "⏰ [Print name] at [time] ET today — defer new entries until post-print reaction" and continue to Step 2.

## Step 1c: TSMC Monthly Revenue (release window only)

TSMC publishes consolidated monthly revenue around the 10th of each month — a clean leading indicator for the global semi cycle (NVDA / AMD / AVGO / MRVL / ASML / AMAT all foundry-downstream). Trigger window: **today is between the 5th and 15th of the calendar month**. Outside that window, skip this section.

In window, call `get_tsmc_monthly_revenue months=13`. Read the freshness line:
- **✅ fresh print** (latest row = prior calendar month) → surface latest YoY + MoM and flag against the 12-month trajectory: a positive YoY surprise vs the prior 3-month run-rate is bullish for the semi tape (especially NVDA / AMD ahead of their reports); a negative surprise or YoY decel >5pp is a warning for any short-dated long-semi exposure.
- **⏰ awaiting print** (latest row is older) → flag "⏰ TSMC monthly revenue release pending (typically ~10th ET morning) — defer new semi-tape entries until post-print" and continue.

Do NOT pre-bake an interpretation. Surface the table; let the user judge whether a single print marks acceleration vs noise. Cross-reference active semi positions and pipeline names from Step 2 / Step 3.

## Step 1d: DIX / GEX Triggers (conditional)

Call `get_dix_gex` daily — SqueezeMetrics' dark-pool flow (DIX) + dealer gamma (GEX). Most days nothing actionable changes; **surface this section ONLY if at least one trigger below fires**, otherwise skip entirely. Do NOT surface "no triggers" / "all clear" — silence is the signal.

Triggers (read from tool output):

1. **GEX sign flip vs prior trading day** (compare last two rows of 10-day trend table)
   - Positive → negative: surface "🔴 GEX flipped negative ($prior → $current). Realized vol now amplifies flow — sell-offs and squeezes both more violent. Hedges become reactive, not preemptive."
   - Negative → positive: surface "🟢 GEX flipped positive ($prior → $current). Vol-suppression returns — short-vol structures more attractive again."

2. **GEX 1m percentile ≥95 or ≤5** (read "1m" row, "GEX %ile" column from percentile context table)
   - ≥95: surface "🟢 GEX 1m %ile [N] — extreme dealer suppression. Cheap-hedge window if under-hedged; CC premium thin (low write attractiveness)."
   - ≤5: surface "🔴 GEX 1m %ile [N] — extreme dealer amplification. Avoid new long-delta; prefer defined-risk structures."

3. **DIX single-day move ≥0.03 in absolute value** (compare last two rows of 10-day trend table)
   - Surface "⚠ DIX moved [signed delta] in one session ([prior] → [current]). 1m %ile now [N]th — [distribution into strength / accumulation into weakness / large institutional flow shift] potentially active."

4. **Divergence flag fires** (tool prints "⚠ Bullish/Bearish divergence" line if active — surface verbatim)

If multiple triggers fire (often correlated), surface all relevant lines. Cross-reference firing triggers with Step 1's regime call (Vol/Tape/Sentiment dimensions) and any vol-sensitive positions in Step 2 — the interaction matters more than the trigger in isolation. Full overlay (regime cell, percentile table, source caveats) lives in the biweekly review; daily is alert-only.

## Step 1e: NAAIM Crowding Trigger (conditional)

Call `get_naaim_history` daily — active-manager equity exposure with 52w z-score. NAAIM is a slow-moving weekly gauge (Wednesday afternoon update); most days it sits inside its band and the value is stale. **Surface this section ONLY if |z-score| ≥ 1.5**, otherwise skip entirely. Do NOT surface "no trigger" / "neutral".

Triggers (read z-score and exposure from tool output):

1. **z ≥ 2.0**: surface "🔴 NAAIM GREEDY (z = +X.XX, exposure XX.X — crowded long, contrarian bearish). Active managers near max-long; positioning stretched. Pairs with any AAII spread > +20 or CBOE p/c < 0.55 to confirm crowding."

2. **z ≥ 1.5** (and < 2.0): surface "🟡 NAAIM stretched long (z = +X.XX, exposure XX.X). Crowding building — not yet extreme. Cross-check with COT SPX/NDX z-scores from Step 1."

3. **z ≤ -2.0**: surface "🔴 NAAIM CAPITULATION (z = -X.XX, exposure XX.X — max defensive, contrarian bullish/squeeze setup). Active managers fully de-risked; counter-trend rallies become explosive."

4. **z ≤ -1.5** (and > -2.0): surface "🟡 NAAIM stretched defensive (z = -X.XX, exposure XX.X). Positioning capitulating — not yet extreme. Watch for squeeze fuel building."

NAAIM is weekly so the same trigger may fire several days in a row until the print updates or the value drifts back inside the band — that persistence is itself informative ("still crowded"). Cross-reference with Step 1's Sentiment dimension and any vol-sensitive positions in Step 2. Full surfacing (WoW change, 8-week trend, multi-window context) lives in the biweekly review.

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

Daily health check on the structural tail hedge. Surfaces whether one of the three playbook triggers is approaching — full evaluation lives in `/hedge`. Per [tail-hedge-playbook.md](../../docs/tail-hedge-playbook.md), do NOT open/close/resize based on regime, vol, or signals.

Call `get_portfolio_greeks` (with `fidelity_folder` if provided). For each long SPY/QQQ put, call `get_quote greeks=True` for current delta.

Present a snapshot: contracts, strike % OTM, current put delta, DTE, P&L %.

Flag only against playbook triggers:
- **DTE ≤ 30** → Trigger 3 (routine roll). Run `/hedge`.
- **Put delta -0.20 to -0.40** → Trigger 1 (maintenance roll) candidate. Run `/hedge`.
- **P&L ≥ +400%** → Trigger 2 (harvest tranche) live. Run `/hedge` immediately.
- **Strike <15% OTM** → Legacy correction-zone; migrate to 25% OTM next maintenance window.
- **No hedge in book** → One-time program-commit decision, not a daily signal call. Run `/hedge` Step 5.

Do NOT flag on cleared signals, vol normalizing, premium decay, or drawdown anxiety — none are valid close reasons. No triggers + hedge exists → **"Hedge healthy, hold."**

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
- **Watch**: regime shifts, upcoming earnings, IV changes, **upcoming NFP/CPI/PCE/GDP/FOMC within 7 days** (from Step 1b's `get_upcoming_economic_releases` output) — defer new entries the day before

No more than 10 items total. If nothing is actionable, say so — "all clear" is a valid briefing.

After presenting the summary, offer to record any new action items as decisions via `decision_add` (with source "briefing" and appropriate deadlines). Also offer to close any pending decisions that are now resolved.
