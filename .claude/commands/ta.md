---
description: Technical-analysis primitives — entry timing, strike anchoring, roll diagnostic, tranche levels, IPO Phase classification, selloff gate
arguments:
  - name: symbol
    description: Ticker (e.g. ADBE, CBRS). Use "SPY" or omit for `selloff` mode.
    required: true
  - name: mode
    description: Sub-mode — omit for default (timing); or `ipo` / `roll` / `tranches` / `strike` / `selloff`
    required: false
  - name: extra
    description: Mode-specific args — `<strike> <expiry>` for roll; `<intent> <delta>` for strike
    required: false
---

Technical-analysis read for **$ARGUMENTS.symbol** in mode **$ARGUMENTS.mode** (default: timing).

## Role and guardrails — read first

This skill produces **price-level outputs** (entry levels, strike anchors, roll timing, phase reads). It does **not** issue thesis verdicts. The framework subordinates technicals to fundamentals (decision-framework.md Step 2) — this skill enforces that subordination, not fights it.

Four guardrails apply to every mode:

1. **Fundamentals override.** If `get_entry_signals` returns conviction Negative AND mode is not `ipo` (which has its own bear path) and not paired with bearish intent in `strike` mode, **stop and surface a one-line refusal**: *"$ARGUMENTS.symbol: conviction is Negative — TA timing read declined. Run /analyze first; if bearish intent is confirmed, re-invoke with --strike intent=put."* Do not proceed.
2. **Fast-track refusal in `ipo` mode.** If an index-inclusion catalyst date sits inside the current Phase-2 window, the Phase-2 fade signal refuses to fire — surface the refusal explicitly per `ipo-lifecycle-playbook.md` carve-out.
3. **IV Rank suppressed for sub-1-year names.** If `get_iv_metrics` shows the underlying has < 52 weeks of IV history (rank/percentile in the low single digits regardless of level), surface the **raw IV Index level** as the timing signal, not rank.
4. **Volume context per mode.** In `ipo` mode, fading volume *confirms* the Phase-2 drift (a spike signals a different event). In `selloff` mode, fading volume *signals capitulation exhaustion*. The interpretation is mode-bound — do not flip it.

## Step 1: Mode dispatch and shared fetch

Parse `$ARGUMENTS.mode`. If empty, treat as `default` (timing). Valid modes: `default`, `ipo`, `roll`, `tranches`, `strike`, `selloff`.

Shared fetch (all modes except `selloff`):
- `get_tradier_history` for $ARGUMENTS.symbol — daily, last 90 sessions (for S/R + range structure)
- `get_tradier_history` weekly, last 52 weeks (for trend + drawdown from 52w high)
- `get_technical_indicators` — default set (sma/ema/rsi/macd/bbands/atr/adx/obv), daily. **Add opt-in indicators per mode**: `donchian` (always useful for mechanizing S/R), `mfi` (ipo mode), `stochrsi` (selloff mode), `hv` (default + when IV-HV spread is the trade thesis).
- `get_iv_metrics` — current IV Index + Rank + IV-HV spread + earnings date + liquidity rating
- `get_entry_signals` — pulls in conviction, circuit breakers, Tape Pattern tag (already computed, don't re-derive)

For `ipo` mode, also pull daily history **since IPO date** (need the day-1 close, post-IPO peak, and the post-IPO range low) and call `get_anchored_vwap symbol=$ARGUMENTS.symbol anchor_date=<IPO date>` — the AVWAP-from-IPO is the institutional cost-basis level Phase-2 fades respect. For `selloff` mode, see Step 6 below — different fetch entirely.

Apply guardrail #1 here, before any further work.

## Step 2: The six primitives (compute once, surface per mode)

These are the building blocks. Every mode consumes a subset.

1. **Drawdown.** From `get_entry_signals` (drawdown_pct) and `get_conviction_metrics` if invoked. Surface: % off 52w high, % off recent peak (if recent peak < 52w high), % off entry/cost basis if a position exists (skip otherwise).

2. **Trend classification + strength.** Use the **Tape Pattern tag** returned by `get_entry_signals` directly — *Rally → Gap-Down, Selloff → Gap-Up, Steady Rally, Steady Decline, Choppy, Quiet, Gap-Up, Gap-Down, Drift*. Do not re-derive. Pair it with: current price vs SMA20 / SMA50 / SMA200 (from `get_technical_indicators`), and weekly vs daily MA alignment (price > 50w SMA = weekly uptrend). **Quantify strength with ADX(14)**: <20 ranging (mean-revert / harvest-premium structures fit), 20-25 transitional, >25 trending (don't fade, don't average down against +DI/-DI dominance), >40 strong trend. ADX direction (+DI vs -DI) confirms the Tape Pattern label.

   **Fallback for short-history names** (sub-1-year, sub-30-session, or freshly IPO'd): `get_entry_signals` may omit the Tape Pattern tag and `get_technical_indicators` may return empty SMA/RSI/ATR/ADX cells (these need ≥14-28 bars; ADX needs ~28+). Derive trend manually from the available daily bars: count closes above vs below the running mean of recent closes, identify gap days (open vs prior close > 2%), and label the tape descriptively (e.g. *"5 down-closes in 7 sessions with one mid-week bounce — selloff-and-fail"*). State the bar count and the limitation explicitly: *"Trend derived from N bars — formal Tape Pattern + ADX unavailable."*

3. **Momentum + volume confirmation.** RSI(14) value + zone (oversold <30 / overbought >70 / neutral). MACD line vs signal (cross direction). Both from `get_technical_indicators`. **Volume confirmation via OBV**: surface the OBV 20d delta direction vs the 20d price direction. Divergences (price up + OBV flat/down, or price down + OBV up) are early-warning signals — call them out explicitly. In low-float / IPO names use **MFI(14)** in place of plain RSI — volume-weighted momentum filters out price-only noise. In `selloff` mode add **Stochastic RSI** for faster oversold detection than RSI(14) catches.

4. **Support / Resistance.** Anchor with the **Donchian channels** from `get_technical_indicators donchian` — 20-day high/low for tactical S/R, 55-day high/low for structural levels. Then refine by reading the last 60-90 sessions of daily OHLCV for:
   - **Round-number psychological levels** ($100, $250) inside the Donchian range.
   - **Prior consolidation floors / breakdown levels** (now resistance) the channel alone won't surface.
   - **Range definition**: if the stock is range-bound, surface the upper and lower bounds and where current sits inside the band (also confirmed by Bollinger %B from `get_technical_indicators`).

   State levels as price points, not vague descriptions ("$275 ceiling tested 3x in the last 30 sessions" — not "around the $270s"). When an **anchored VWAP** is relevant (post-IPO, post-earnings, post-peak), pull `get_anchored_vwap` with the right anchor and treat it as a primary level — institutional cost basis trumps swing-level pattern reads.

5. **ATR / realistic move band + realized vol context.** Raw ATR(14) from `get_technical_indicators`. Surface as % of current price, and use it to bracket realistic moves:
   - 1× ATR = average daily range
   - ATR × √(N) = approximate 1σ N-day band
   - Always cross-reference against `get_expected_move` if options-relevant — implied move is the option-market consensus and overrides historical ATR when both are available.

   When IV environment drives the strategy decision (defined-risk-exposure, harvest-premium, bet-on-volatility), also pull `get_technical_indicators hv` and read the **HV term structure (10d / 30d / 60d)**: rising shape (HV10 > HV30 > HV60) confirms IV richness is justified; cooling shape (HV10 < HV30 < HV60) with elevated IV = real premium-selling edge.

6. **IV Index level + trend.** From `get_iv_metrics`. If the underlying has < 52w IV history, **suppress IV Rank** in the output (apply guardrail #3) and surface the raw IV Index level only, with the note: *"IV Rank/Percentile unreliable on sub-1-year history — read IV Index level."* Cross-check against the HV term structure (#5) — IV-HV spread is a level read, but spread direction over the last 2-4 weeks is the trade signal.

## Step 3 — Mode `default` (timing read on an approved trade)

Use this after `/analyze` Step 4 approves a trade. Output:

- **Phase line.** One sentence: trend label (from #2) + ADX zone + MA posture + RSI zone + recent 2W net %. *e.g. "ADBE: Steady Rally tag, ADX 28 trending (+DI dominant), price > SMA20/50 but < SMA200 (weekly downtrend intact), RSI 58, +6% last 2W."*
- **Levels.** Donchian 20d/55d bounds, nearest support, nearest resistance, current % from each. Mark which side dominates ("closer to resistance — entry is fighting the cap"). If a prior peak / earnings date is a relevant anchor, surface the AVWAP from that date.
- **Realistic move band.** ATR-derived 2-week and 2-month 1σ ranges, plus HV term structure if it's informing the strategy choice. Cross-check expected move if options-active.
- **IV environment.** IV Index level + trend, IV-HV spread + direction, IV Rank (or its suppression). Reference to strategy-catalog's IV-HV shift columns.
- **Volume read.** OBV 20d delta vs price 20d % — call out any divergence by name (don't bury it in a table).
- **Entry guidance — one of three verdicts:**
  - **Entry-ready** — structure supports the trade now (e.g., approved Accumulate, price at support, IV environment matches strategy choice).
  - **Wait for confirmation** — name the trigger ("wait for daily close above $X" / "wait for RSI to roll over from current 72" / "wait for ADX to drop below 25 before fading").
  - **Scale in** — if Accumulate intent, hand off to `tranches` mode for explicit T1/T2/T3 levels.
- **One-line invalidation.** What price/structure change would invalidate the *timing* (not the thesis) — e.g., "break of $260 support cancels this entry; re-evaluate."

## Step 4 — Mode `ipo` (Phase classification + rollover-confirmation primitive)

Reference: `ipo-lifecycle-playbook.md`. Use when the name is < 12 months public and the thesis hinges on an IPO-mechanics catalyst.

**Step 4a: Phase classification.** Compute and surface:
- IPO date, weeks since IPO, IPO price, day-1 close.
- Post-IPO peak (highest close since IPO) and the date.
- Current price + % off post-IPO peak.
- Phase label per the playbook arc:
  - Phase 1 (day 0 → ~wk 6): pop and flip
  - Phase 2 (mo ~1 → ~5): premium decay
  - Phase 3 (mo ~5 → ~7): dead zone
  - Phase 4: fundamental re-rate (event-driven, not time-driven)

**Step 4b: Fast-track contamination check.** Apply guardrail #2. The contamination window is **day 0 through ~month 5 from IPO** (Phase 1 plus Phase 2) — the playbook addendum says a forced index bid landing anywhere in this span breaks the demand-exhaustion driver of the slow bleed.

Detect a fast-track / index-inclusion catalyst by **two passes**:

1. **Structured catalysts.** Call `pipeline_catalyst_list ticker=$ARGUMENTS.symbol`. Match catalysts where `type` ≈ index inclusion (currently typed as `other` — match on description keywords: *"fast track"*, *"index inclusion"*, *"S&P 500"*, *"Nasdaq-100"*, *"NDX fast entry"*, or *"index fund"*).
2. **Free-text fallback.** Call `pipeline_get ticker=$ARGUMENTS.symbol` and scan the `entry_plan`, `thesis`, and `watch_items` fields plus recent notes for the same keywords. Free-text mentions are common because the catalyst typing schema doesn't have a dedicated `index_inclusion` value yet. **If a free-text mention is found but no structured catalyst exists, flag it: "📋 Index-inclusion catalyst found in free text but not structured — recommend `pipeline_catalyst_add type=other` for cleaner future detection."**

If any catalyst (structured OR free-text) has a date inside day 0 through ~month 5 from IPO, **refuse the Phase-2 fade read**:
  > 🛑 **Phase-2 fade declined — fast-track contamination.** [Index inclusion date] sits inside this name's contamination window (Phase 1 + Phase 2). Per `ipo-lifecycle-playbook.md` carve-out, the forced index bid breaks the demand-exhaustion driver of the slow bleed. Trade the first-print event instead (Phase 4 catalyst).

Continue to Step 4c only if no contamination, OR if the user invoked with bullish intent (Phase 3 accumulation read still valid even under contamination).

**Step 4c: Rollover-confirmation primitive (bearish entry).** Execute the playbook test literally:
- Identify the **post-IPO range low** — the lowest daily close from week 1 through the most recent low before the current bounce (if any).
- Count **lower highs**: rallies since the post-IPO peak where each peak < the prior bounce high.
- Count **closes below the post-IPO range low**.
- **AVWAP-from-IPO context**: pull `get_anchored_vwap anchor_date=<IPO date>` — a close decisively below the AVWAP (with price spending 60%+ of recent sessions below) is the institutional-cost-basis break and adds an independent rollover vote.
- **OBV confirmation**: a falling OBV during the rollover (institutional distribution) is required for high-confidence rollover; rising OBV with falling price = bullish divergence and *invalidates* the rollover read.
- Verdict:
  - ≥ 2 lower highs AND ≥ 2 closes below range low → **"Rollover confirmed."**
  - 1 close decisively through the range low (close > 2% below it) AND AVWAP-from-IPO broken → **"Rollover confirmed (single-leg break)."**
  - Otherwise → **"Not confirmed — still ranging."**

**Step 4c-alt: Phase 3 accumulation read (bullish intent).** If the user is bullish on this name:
- Has the Phase-2 trough been put in? Compute: largest drawdown from post-IPO peak, time since that low, current bounce magnitude.
- AVWAP-from-IPO: a reclaim of the AVWAP after a sustained period below is a Phase-3-to-Phase-4 transition tell.
- Verdict: "Dead zone confirmed" (range-bound for 3+ weeks at the lows, IV crushed, AVWAP overhead but flattening) → accumulation window open. Otherwise "Phase 2 still in progress" → wait.

**Step 4d: IV signal.** Apply guardrail #3 — for sub-1-year, surface IV Index level only, suppress Rank. Note: post-IPO IV peaks days/weeks after listing, crushes over months 1-3, re-inflates into each earnings date. Cross-check with `hv` term structure — a low HV10 against high IV in a Phase-2 name means options market is still pricing the IPO uncertainty premium.

**Step 4e: Volume context.** Apply guardrail #4 — fading volume on a Phase-2 drift is *confirming*, not a warning. A volume **spike** signals a different event (earnings, news, inclusion) and the read above does not apply to that bar. Flag spike bars explicitly if present. **MFI(14)** read: in Phase 2, MFI typically pins low (volume-weighted selling pressure dominant); an MFI reclaim above 40 with price still range-bound is an early accumulation tell.

## Step 5 — Mode `roll` (CC/CSP roll-timing diagnostic)

Args: `$ARGUMENTS.extra` parses as `<strike> <expiry>` (e.g. `230 2026-06-18`).

Pull the position's chain via `get_option_chain` for $ARGUMENTS.symbol at the given expiry, find the short leg, surface its current delta and extrinsic value. Compute current price vs strike and % from strike.

Diagnose against `covered-call-overlay.md` Step 6b roll-timing table:

| Signal | Verdict |
|---|---|
| Short-call delta ~75-80 (or short-put delta -.75 to -.80) | **Evaluate roll now** — past this, intrinsic dominates and roll economics deteriorate |
| Short delta > 80 (extrinsic < 20% of premium) | **Approaching roll-too-late** — surface debit-roll budget gates |
| Stock gapped > 3% in last session | **Wait 1-2 days** — spreads inflated by short-term vol |
| Sustained rally > 15% in 2W AND short leg > 10% ITM | **Roll on next flat or red day** — don't wait for a pullback that may not come |
| Gradual grind, no gap | **Roll when ready** — no spread distortion |
| Stock dropped significantly since write (CC underwater) | **Buy back at 80%+ profit, reassess** — don't write at lower strike on momentum |
| Earnings within 14 days AND CC < 50% profit | **Buy back** — gap risk > remaining premium |

Cross-reference IV Rank (from shared fetch) — elevated IV (> 30%) favors rolling now (richer new leg). Suppress IV Rank if sub-1-year.

**ADX gate.** Before recommending a same-direction roll into a strong move, check ADX: if ADX > 30 and +DI/-DI alignment confirms the move against the short leg, surface the warning *"strong trend in motion (ADX X, +DI/-DI Y/Z) — same-strike roll likely re-tests this within the roll's DTE; consider closing-and-reassessing instead."* This catches the late-cycle melt-up scenario where CCs cap upside repeatedly.

**Hand off:** end with a one-line recommendation to call `analyze_roll` with 2-3 candidate strike/expiry combos, and to pass `chain_credits` from `get_cc_chain_pnl` for the debit-budget verdicts. Do not place the roll — that's a separate explicit step.

## Step 6 — Mode `tranches` (scale-in entry levels)

Use this after `/analyze` approves **Accumulate** intent and a multi-tranche plan. Generates concrete T1/T2/T3 price levels.

- Pull drawdown from peak (primitive #1).
- Pull Donchian 20d/55d lows (mechanical S levels), nearest swing support, ATR (primitives #4-5).
- **ADX gate**: if ADX > 30 with -DI dominant, surface the warning *"strong downtrend in motion — T2/T3 should fire only after ADX cools below 25 OR after a confirmed reversal candle. Don't average down into capitulation that hasn't capitulated."*
- Output structure:
  - **T1** at current market (or first identified support if current is at resistance) — sized per the Accumulate matrix in strategy-catalog.md
  - **T2** at the next support below — or the Donchian 20d low — or current × (1 − 1.5 × ATR-derived 2W band) if no clean structural level
  - **T3** at the Donchian 55d low or second swing support — reserved for deeper drawdown ("if X breaks $Y, T3 fires at $Z")
- Each tranche: price level + structural reason (cite the Donchian level or swing low explicitly) + approximate dollar/share sizing (use `calculate_position_size` if specific portfolio context is known).
- One-line tranche philosophy reminder: T2 is not a "down-buy" reflex — re-check the thesis at each level before firing, and re-read ADX at each tranche.

## Step 7 — Mode `strike` (strike anchoring at structure)

Args: `$ARGUMENTS.extra` parses as `<intent> <delta>` (e.g. `CSP 0.30`, `CC 0.20`, `put 0.30` for protective puts).

Pull `get_option_chain` for $ARGUMENTS.symbol — preferably the front-month or specified expiry. For each intent:

- **CSP** (entry-at-discount): find strikes at target delta, then anchor against nearest support **below current**. Prefer the strike that sits *below* a clean support level (assignment lands you below structure, not into a falling knife). Surface 2-3 candidates with delta + distance from support + premium + annualized yield.
- **CC** (income / growth-with-income / orderly liquidation): find strikes at target delta, anchor against nearest resistance **above current**. Prefer the strike at or just below a clean resistance (call gets called away at the cap, where you'd sell anyway).
- **Protective put** (hedge): find strikes at target delta, anchor against ATR-derived realistic worst-case (event hedge) OR recent swing low (positional hedge). Surface 2-3 candidates with delta + % OTM + cost + % portfolio.

For all three, **never recommend a single strike** — always 2-3 candidates with the trade-off named ("$225 is the pure-binary cheaper alternative at -0.22 delta; $230 sits above $228 support, -0.31 delta, $185 cost"). Let the user pick.

Reference: `protective-put-collar-playbook.md` for hedge-specific strike rules; `covered-call-overlay.md` Step 4 for CC delta-by-intent; `strategy-catalog.md` Enter-at-Discount section for CSP drawdown table.

## Step 8 — Mode `selloff` (SPY/QQQ recovery entry gate)

Reference: `selloff-recovery-playbook.md` Leg 1.

Fetch in parallel:
- `get_market_regime` (full)
- `get_quote SPY,QQQ,VIX,XLY,XLU`
- `get_tradier_history SPY` last 30 sessions
- `get_entry_signals SPY` for RSI + Tape Pattern + circuit breakers
- `get_technical_indicators SPY` (SMA50 specifically)

**Gate 1:** SPY drawdown from 52w high > 7%? (Yes/No)

**Gate 2 (need ≥ 2):** VIX > 25, SPY < SMA50, XLY/XLU ratio falling (risk-off).

**Gate 3 trigger classification.** Ask the user (or read from active macro overhangs in MEMORY.md) — exogenous shock / structural-liquidity / policy-geopolitical / macro-rates / earnings-fundamental. This determines whether to lean calls or CSPs (per the playbook table).

**The 5-signal entry check (need 3 of 5):**

| Signal | Read |
|---|---|
| RSI oversold (with Stoch RSI fast confirmation) | SPY RSI < 30, **and** Stoch RSI %K < 20 (faster oversold from `get_technical_indicators stochrsi`) — Stoch RSI turning back up from <20 is the actionable trigger |
| VIX term-structure flip | VIX > 30 AND VIX3M reclaiming the lead — **strongest single signal** |
| Breadth stabilizing | XLY/XLU ratio bottoming or turning up (manual read from quotes) |
| Volume exhaustion (OBV reclaim) | SPY daily volume declining from capitulation peak for 2+ days, **and** OBV stops making new lows even as price tests them (bullish divergence from `get_technical_indicators obv`) |
| Sentiment capitulation | Wall-to-wall bearish coverage (`get_news_sentiment SPY`) |

Note: VIX3M isn't directly tooled — surface the limitation and ask the user to read it from the broader vol-surface context (or skip and flag it as an unverified signal).

**Verdict:**
- 0-2 signals firing → **Not ready.** Specify what's still missing.
- 3+ signals firing → **Recovery-call entry window open** — name the strike/DTE/sizing per the playbook (delta 0.40-0.50, DTE 45-60, max 3% premium-at-risk).
- Always cross-reference: is the CSP leg already in motion on conviction pipeline names? Recovery calls + CSP collateral combined ≤ 70% capital.

Apply guardrail #4 here — fading volume is the *exhaustion* signal in this mode, not a confirming drift signal.

## Final output format

End every mode with:

**$ARGUMENTS.symbol TA Read — mode: [mode]**
- **Primitives**: [trend tag] | [RSI zone] | [drawdown%] | [nearest S/R] | [ATR-derived 2W band] | [IV Index trend]
- **Verdict**: [the mode's specific verdict — entry-ready / wait / refuse / Phase X / 3-of-5 / etc.]
- **Action**: [the concrete next step — a price level, a wait condition, a strike candidate set, a roll diagnosis]
- **Invalidates if**: [the one price/structure change that breaks the read]

Keep the read tight. The skill produces price levels, not narrative.
