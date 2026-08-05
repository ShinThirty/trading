---
description: Portfolio-wide covered call scan — find positions ready for new CCs
---

Scan all equity positions across accounts and identify which ones are ready for a new covered call write today.

## Step 1: Gather All Positions

1. Enumerate equity positions across accounts:
   - `get_webull_positions` per Webull account (`get_webull_accounts` to list them).
   - `get_snaptrade_positions` (spans all Fidelity accounts).
2. Build a list of all equity positions, noting:
   - Which already have CCs (COVERED_STOCK strategy)
   - Which are uncovered shares
   - Share count per position (determines max contracts)

## Step 2: Filter — When NOT to Write

For each **uncovered** equity position, check the CC overlay "When NOT to write" rules (docs/covered-call-overlay.md CC Step 2). Disqualify positions that hit any of these:

| Filter | Check | Tool |
|--------|-------|------|
| **Still accumulating** | Is this ticker in the pipeline with status LIVE or PIPELINE and intent accumulate/enter-at-discount? | `pipeline_list` |
| **Pre-catalyst** | Earnings within 2 weeks? | `get_iv_metrics` (earnings date) |
| **IV Rank too low** | IV Rank < 25%? Premiums not worth capping upside. Exception: thesis exits. | `get_iv_metrics` |
| **Deep underwater** | Current price >20% below cost basis? | Position cost vs last price |
| **First 2 weeks** | Was this position entered within the last 14 days? | `get_webull_order_history` or skip if unclear |

Call `get_iv_metrics` in a single batch for all uncovered symbols to check IV Rank, earnings dates, and liquidity in one call. **In parallel**, call `get_equity_risk_premium` and `get_yield_curve_state` — these flex Step 3 coverage and Step 4 strike aggressiveness. Note the ERP tier and curve regime; carry forward.

**VRP check on the survivors.** After the filter table, call `get_variance_risk_premium` for each position still READY (these are usually few — call them in parallel). A CC is a short-premium trade, so selling into **Cheap** vol (<0.95) means capping upside for less than the cap is worth:

| VRP read | Effect |
|---|---|
| **Rich** / **Modestly rich** (≥1.10) | Proceed — the cap is being well paid for |
| **Fair** (0.95-1.10) | Proceed only on thesis-exit or oversized-position intent, where the cap is the *point* and premium is incidental |
| **Cheap** (<0.95) | **Skip the income and growth+income writes.** Thesis exits still proceed — you want the shares gone regardless of what the premium pays |

This is a sharper version of the existing IV Rank < 25% filter and takes precedence where they disagree: IV Rank asks "is IV high for this name," VRP asks "is IV above what the name actually realizes," and only the second one determines whether the premium compensates the cap.

**Valuation-regime relaxation on the IV Rank filter:** At **Compressed-Negative ERP** OR **Bear Steepener with long end leading**, the IV Rank < 25% filter is loosened — write even at lower IV. Reason: caps are protecting against likely downside, not just capping unlikely upside. Multiple expansion is mechanically improbable in those regimes, so writing thin-premium CCs still earns their keep. Keep the filter strict at **Generous ERP** / **Bull Steepener** (multiples have room — don't cap for low premium).

Present the filter results as a table:

| Symbol | Shares | Cost | Last | P&L % | IV Rank | Earnings | Filter Result |
|--------|--------|------|------|-------|---------|----------|---------------|
| ... | ... | ... | ... | ... | ... | ... | READY / [reason skipped] |

## Step 3: Score Candidates

For each READY position:

1. `get_entry_signals` for conviction, RSI, circuit breakers.
2. Determine CC intent: thesis exit (oversized/timeline ending), growth with income (still bullish, want premium), or income generation (range-bound).
3. Map conviction to coverage per CC Step 3 in [covered-call-overlay.md](../../docs/covered-call-overlay.md): 100% (exit) / 75-100% (neutral) / 50-75% (bullish) / 0-25% (high conviction breakout).
4. **Valuation-regime flex on coverage:**
   - **Compressed-Negative ERP** OR **Bear Steepener (long end leading)** → shift one bucket *up* (e.g., bullish 50-75% → 75%; neutral 75-100% → 100%). Multiple expansion mechanically improbable; capping more upside is the right call.
   - **Generous ERP** OR **Bull Steepener** → shift one bucket *down*. Multiples have room; don't cap a likely rally.
   - **Tight / Fair ERP + Quiet / Mixed curve** → no shift; coverage stands per conviction.
   - This is regime-conditional and explicitly inverts the `feedback_cc_loss_close.md` lesson when regime is hostile (no melt-up = caps are insurance, not opportunity cost).
5. If coverage 0%, skip.

## Step 4: Strike and Expiry Selection

For each candidate with coverage > 0%:

1. `get_option_expirations`.
2. Pick expiry: post-earnings window → 30-45 DTE (best); earnings 3-6 weeks away → sell through to capture IV; otherwise 30-45 DTE (no 8+ month CCs).
3. `get_option_chain` at chosen expiry, `strike_count=8`. Target delta: thesis exit → exit price; income → 15-20 delta; growth+income → 25-30 delta.

   **Valuation-regime delta flex:**
   - **Compressed-Negative ERP** OR **Bear Steepener (long end leading)** → bias *higher delta* within range (income → 20; growth+income → 30). Multiple expansion improbable; tighter strikes capture more premium without giving up much expected upside.
   - **Generous ERP** OR **Bull Steepener** → bias *lower delta* within range (income → 15; growth+income → 25). Wider OTM preserves room for multiple expansion.
   - **Tight / Fair ERP + Quiet / Mixed curve** → midpoint of range.
   - See [valuation-regime.md](../../docs/valuation-regime.md) for the full framework.
4. Present: premium (bid), delta, % OTM, annualized yield, earnings interaction.

## Step 5: Existing CC Check

For positions that **already have CCs**, check management triggers:

| Trigger | Condition | Action |
|---------|-----------|--------|
| >50% profit | Current price < 50% of sold premium | Buy back, rewrite |
| >80% profit | Current price < 20% of sold premium | Buy back — not worth the risk |
| Expiring <14 DTE | DTE remaining < 14 | Close, roll, or let expire |
| Approaching strike | Stock within 5% of strike | Evaluate: roll up or let assign |
| Earnings approaching | Earnings within 14 DTE of CC expiry | Buy back if <50% profit — gap risk |

## Final Output

### CC Write Candidates

| Symbol | Shares | Coverage | Contracts | Intent | Strike | Exp | DTE | Delta | Premium | Ann. Yield | Action |
|--------|--------|----------|-----------|--------|--------|-----|-----|-------|---------|-----------|--------|

### Existing CCs — Management Alerts

| Symbol | Strike | Exp | DTE | % Profit | Alert | Action |
|--------|--------|-----|-----|----------|-------|--------|

### Skipped Positions

| Symbol | Reason |
|--------|--------|

For each write candidate, offer to preview the order. For existing CC alerts, offer to run `/roll` on the specific symbol.
