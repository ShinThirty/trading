---
description: Run the full post-screening decision framework (Steps 1-4) for a ticker
arguments:
  - name: symbol
    description: Ticker symbol to analyze (e.g. ADBE, NVDA)
    required: true
---

Run the complete post-screening decision framework for **$ARGUMENTS.symbol**. Execute Steps 1 through 4 in order. Do NOT skip steps or summarize — run every tool call and present every result.

## Step 1: Determine Intent (Conviction → Intent)

1. Call `get_entry_signals` for $ARGUMENTS.symbol. This returns quantitative conviction scores (ROE, Growth, Margins, Cash Flow — each scored Bullish/Moderate/Neutral/Negative), IV metrics, momentum signals, and circuit breaker detection.

2. Present the full output, then assess:
   - **Quantitative conviction**: Summarize the four auto-scored factors. Count how many score Negative.
   - **Circuit breakers**: If any triggered, state the action explicitly (hard stop, proceed, cap size, etc.).
   - **Qualitative factors** (Moat and AI ROI): Provide your assessment based on what you know about the company. If you need more context, call `get_company_news` for $ARGUMENTS.symbol.
   - **If 2+ quantitative factors score Negative**: State "Conviction: Negative — routing to bearish framework" and follow the bearish assessment in docs/bearish-framework.md (deterioration scoring → valuation disconnect → bearish conviction level → L2 strategy selection).

3. Based on the combined conviction assessment, determine the **intent** from this table:

   | Conviction | Intent |
   |-----------|--------|
   | Highest | Accumulate |
   | High | Enter at discount |
   | High, time-specific | Directional leverage |
   | Moderate | Defined-risk exposure |
   | Low / Neutral | Harvest premium |
   | Direction-agnostic | Bet on volatility |
   | Negative | Bearish |

   State: "**Intent: [X]** — [one sentence why]"

## Step 2: Read the Signals

1. Call `get_market_regime` to get the macro context (volatility, trend, macro, sectors).

2. Cross-reference the market regime with the stock-level signals from Step 1. Note:
   - IV environment: Is IV Rank high (>50%, sell premium) or low (<30%, buy premium)?
   - IV-HV spread: >10% (options rich) or <5% (options fair/cheap)?
   - Momentum: RSI, SMA alignment, 2-week price action.
   - Earnings proximity: How close is the next earnings date?
   - Liquidity: Liq rating 1-2 (tight, good) or 3-4 (wide, caution)?

3. If there are signal conflicts, apply the priority hierarchy: fundamentals > IV environment > technicals.

## Step 3: Choose Strategy

Match intent + signals to strategy via the intent→strategy matrix in [decision-framework.md](../../docs/decision-framework.md) Step 3. Detailed mechanics live in [strategy-catalog.md](../../docs/strategy-catalog.md).

For **Accumulate** with 100 shares >$15K, proactively compare LEAPS vs shares. For credit/debit strategies with peer pipeline names, recommend `compare_credit_efficiency` / `compare_debit_efficiency`.

State: "**Strategy: [X]** — [one sentence rationale linking intent + IV]" with specific parameters (strike delta or % OTM, DTE, earnings interaction).

## Step 4: Size the Position

Use the size tier already computed by `get_entry_signals` (Full/Standard/Reduced). Present:
- The sizing tier and its allocation percentage (Full=10%, Standard=5%, Reduced=2%)
- Any modifiers: circuit breakers that cap size, FOMO trap reducing tier, etc.
- Reminder: reserve cash for T2 scale-in, 60% CSP collateral cap, max 15% single-name concentration.

## Final Output

End with a concise action plan:

**$ARGUMENTS.symbol Action Plan**
- **Intent**: [intent]
- **Strategy**: [specific strategy with parameters]
- **Size**: [tier]
- **Key risk**: [the one thing that could invalidate this trade]
- **Next step**: [what to do next — e.g., "run get_option_chain for strike selection" or "wait for post-earnings entry"]
