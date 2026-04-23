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
   - **Must be a net credit.** If all candidates require a debit, state this and recommend alternatives (let assign, buy back).
   - **Don't roll past thesis end date.** Flag if any candidate expiry extends beyond the thesis timeline.
   - **Roll before earnings** if the current option goes through earnings and you want to avoid assignment on a gap.

## Step 4: Chain P&L Check

1. Call `get_cc_chain_pnl` for $ARGUMENTS.symbol with the appropriate account_id and option_type (call for CCs, put for CSPs). This traces all filled option orders from Webull order history, sums credits vs debits, and shows chain P&L.

2. Assess:
   - Is the chain net positive or negative?
   - Would this roll keep the chain net positive?
   - If the chain is already net negative, flag: "Chain loss exceeds benefit — consider stopping the roll cycle."
   - For CCs: a losing chain is fine if shares gained more. For CSPs: a losing chain is a warning (you paid more to avoid assignment than you collected).

## Final Output

**$ARGUMENTS.symbol Roll Decision**
- **Current position**: [strike, expiry, DTE, % profit]
- **Recommendation**: [roll / let assign / buy back]
- **Best roll**: [new strike, new expiry, net credit] (if rolling)
- **Chain status**: [net credit/debit across all rolls]
- **Next step**: [specific action — e.g., "preview the roll order" or "let this expire worthless"]

Offer to record the decision via `decision_add` with source "roll" and the appropriate action (ROLL, ASSIGN, or CLOSE). If ROLL, also offer to create a `roll_add` entry and link it via `roll_id`.
