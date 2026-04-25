---
description: Portfolio-wide covered call scan — find positions ready for new CCs
---

Scan all equity positions across accounts and identify which ones are ready for a new covered call write today.

## Step 1: Gather All Positions

1. Call `get_account_positions` for the Webull Cash account (5GJ21MGS53M5FU0T8TQN6PEGQA).
2. If the user has fresh Fidelity CSVs at ~/Downloads/fidelity/, read those too.
3. Build a list of all equity positions, noting:
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
| **First 2 weeks** | Was this position entered within the last 14 days? | `get_order_history` or skip if unclear |

Call `get_iv_metrics` in a single batch for all uncovered symbols to check IV Rank, earnings dates, and liquidity in one call.

Present the filter results as a table:

| Symbol | Shares | Cost | Last | P&L % | IV Rank | Earnings | Filter Result |
|--------|--------|------|------|-------|---------|----------|---------------|
| ... | ... | ... | ... | ... | ... | ... | READY / [reason skipped] |

## Step 3: Score Candidates

For each position that passes the filters (READY):

1. Call `get_entry_signals` to get current conviction, RSI, and circuit breakers.
2. Determine CC intent based on the position context:
   - Thesis exit: position is oversized or thesis timeline is ending
   - Growth with income: still bullish, want premium while holding
   - Income generation: range-bound or slow-growth name
3. Map conviction to coverage ratio (CC Step 3):

   | Forward conviction | Coverage | Contracts |
   |---|---|---|
   | Exit / declining thesis | 100% | All shares |
   | Range-bound / neutral | 75-100% | Most shares |
   | Still bullish, want income | 50-75% | Half to three-quarters |
   | High conviction, expect breakout | 0-25% or skip | Few or none |

4. If coverage is 0% (skip), note it and move on.

## Step 4: Strike and Expiry Selection

For each candidate with coverage > 0%:

1. Call `get_option_expirations` for available expiries.
2. Select expiry per CC Step 5:
   - **Post-earnings window (earnings just passed)**: 30-45 DTE — best window
   - **Earnings 3-6 weeks away**: Sell THROUGH earnings to capture IV
   - **Earnings within 2 weeks**: Already filtered out in Step 2
   - Prefer 30-45 DTE per user preference (no 8+ month CCs)

3. Call `get_option_chain` at the selected expiry with `strike_count=8` to find strikes at the target delta:
   - Thesis exit: strike = exit price
   - Income generation: 15-20 delta (~10-15% OTM)
   - Growth with income: 25-30 delta (~8-12% OTM)

4. Present the best strike with:
   - Premium (bid price)
   - Delta
   - % OTM
   - Annualized yield (premium / share price, annualized by DTE)
   - Earnings interaction

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
