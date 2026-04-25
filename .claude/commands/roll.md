---
description: Evaluate and execute an option roll (CC or CSP)
arguments:
  - name: symbol
    description: Underlying ticker symbol (e.g. META, ALAB)
    required: true
---

Evaluate whether to roll an option position on **$ARGUMENTS.symbol** and present roll candidates.

## Step 1: Current Position

1. Call `get_account_positions` to find the current CC or CSP on $ARGUMENTS.symbol. Identify:
   - Option type (call or put)
   - Current strike and expiration
   - Current P&L (% of max profit realized)
   - DTE remaining

2. Call `get_quote` for $ARGUMENTS.symbol to get the current underlying price and distance to strike.

## Step 2: Should This Option Still Exist?

Before looking at roll economics, answer this question based on the position type:

**For CCs** (from docs/covered-call-overlay.md):

| Situation | Right move |
|-----------|-----------|
| Thesis exit, stock approaching strike | Let assign — the strike was your exit price |
| Growth with income, stock approaching strike | Roll up and out — you want to keep the position |
| Thesis broken, stock falling | Buy back CC, sell shares — exit the whole position |
| Income/wheel, stock falling | Roll down for credit — reset at a lower strike |

**For CSPs** (from docs/strategy-catalog.md):

| Situation | Right move |
|-----------|-----------|
| Stock approaching strike, thesis intact, want lower entry | Roll down and out for credit |
| Stock approaching strike, you want assignment | Let assign — this was the plan |
| Thesis broken, stock falling | Buy back and walk away |
| Stock well above strike, CSP at >50% profit | Buy back, write next cycle |

State: "**Recommendation: [roll / let assign / buy back / exit]** — [why]"

If the recommendation is NOT to roll, stop here and explain the rationale.

## Step 2b: Coverage Reassessment (multi-contract positions only)

If the position has 2+ contracts, reassess coverage ratio before deciding how many to roll:

1. Call `get_entry_signals` for $ARGUMENTS.symbol to re-score conviction at today's price.
2. Map forward conviction to coverage ratio (from CC Step 3):

   | Forward conviction | Coverage | Roll action |
   |---|---|---|
   | Exit / declining thesis | 100% | Let all assign |
   | Range-bound / neutral | 75-100% | Roll 75-100%, let rest assign |
   | Still bullish, want income | 50-75% | Roll 50-75%, let rest assign |
   | High conviction, expect breakout | 0-25% | Roll 0-25%, let rest assign |

3. State: "**Coverage: [X of Y contracts]** — conviction is [level] at today's price, [roll N / let M assign]"

For single-contract positions, skip this step — the decision is all-or-nothing.

## Step 3: Roll Candidates

If rolling is appropriate:

1. Call `get_option_expirations` for $ARGUMENTS.symbol to see available expiries.

2. Call `analyze_roll` with 2-3 candidate scenarios:
   - **Same strike, next monthly** (pure time extension)
   - **One strike up/down + next monthly** (diagonal roll)
   - **Two strikes up/down + 2 months out** (aggressive diagonal)

   For CCs: roll UP and out. For CSPs: roll DOWN and out.

3. For each candidate, present:
   - Net credit/debit of the roll
   - New strike and expiration
   - New DTE
   - Distance to new strike (% OTM)
   - Earnings interaction (does the new expiry go through earnings?)

4. Check roll rules:
   - **Prefer net credit.** If a candidate requires a debit, the debit budget analysis (Step 4) determines whether it's justified.
   - **Don't roll past thesis end date.** Flag if any candidate expiry extends beyond the thesis timeline.
   - **Roll before earnings** if the current option goes through earnings and you want to avoid assignment on a gap.

## Step 4: Chain P&L and Debit Budget

1. Call `get_cc_chain_pnl` for $ARGUMENTS.symbol with the appropriate account_id and option_type (call for CCs, put for CSPs). This traces all filled option orders from Webull order history, sums credits vs debits, and shows chain P&L.

2. If any roll candidate is a net debit, re-run `analyze_roll` with `chain_credits` set to the Chain P&L total from step 1. The tool will automatically evaluate:
   - **Gate 1 (chain budget)**: debit ≤ 50% of accumulated chain credits
   - **Gate 2 (vs assignment)**: debit < intrinsic value lost at assignment
   - **Verdict**: PASS / FAIL

3. Assess:
   - Is the chain net positive or negative?
   - Would this roll keep the chain net positive?
   - If the chain is already net negative, flag: "Chain loss exceeds benefit — consider stopping the roll cycle."
   - For CCs: a losing chain is fine if shares gained more. For CSPs: a losing chain is a warning (you paid more to avoid assignment than you collected).
   - If all candidates fail the debit budget, recommend letting assign or accepting the cap.

## Final Output

**$ARGUMENTS.symbol Roll Decision**
- **Current position**: [strike, expiry, DTE, % profit]
- **Recommendation**: [roll / let assign / buy back]
- **Coverage**: [X of Y contracts to roll] (multi-contract only)
- **Best roll**: [new strike, new expiry, net credit/debit] (if rolling)
- **Debit budget**: [PASS/FAIL/N/A] (if net debit)
- **Chain status**: [net credit/debit across all rolls]
- **Next step**: [specific action — e.g., "preview the roll order" or "let this expire worthless"]

Offer to record the decision via `decision_add` with source "roll" and the appropriate action (ROLL, ASSIGN, or CLOSE). If ROLL, also offer to create a `roll_add` entry and link it via `roll_id`.
