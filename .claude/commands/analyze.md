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
   - **Recent-earnings deep-dive prompt**: Determine the most recent earnings date (use the date from `get_entry_signals` output, or call `get_fmp_earnings_calendar` with limit=1 if not visible). If earnings reported within the past **45 days**, pause and ask:
     > 📊 **$ARGUMENTS.symbol reported earnings on YYYY-MM-DD (N days ago).** Want me to pull the call transcript and 8-K press release for a deeper post-earnings re-analysis? This sharpens the qualitative factors (Moat, AI ROI) and surfaces guidance / segment-mix shifts the news cycle hasn't fully digested yet.

     If **yes**, call `get_earnings_transcript` and `get_earnings_release` in parallel, then reference their content when assessing the qualitative factors below and explicitly note any guidance changes or segment-mix shifts that move conviction. If **no** (or earnings >45 days old), proceed with the normal qualitative assessment.
   - **Qualitative factors** (Moat and AI ROI): Provide your assessment based on what you know about the company. If you need more context, call `get_company_news` for $ARGUMENTS.symbol.
   - **If 2+ quantitative factors score Negative**: State "Conviction: Negative — routing to bearish framework" and follow the bearish assessment in docs/bearish-framework.md (deterioration scoring → valuation disconnect → bearish conviction level → L2 strategy selection). Scoring the valuation-disconnect gate needs `get_issuer_credit` — see Step 2 item 1.

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

1. Call `get_market_regime`, `get_equity_risk_premium`, `get_yield_curve_state`, and `get_variance_risk_premium` for $ARGUMENTS.symbol in parallel for full macro + vol-pricing context (regime: Vol/Trend/Breadth/Macro/Sectors/Credit/Tape/Sentiment/Positioning/Policy + ⚠ Extended/Sentiment; ERP tier; curve regime; VRP read). For commodity-linked names, also call `get_cot_positioning` on the relevant contract. For event-driven names (FOMC-sensitive, election, FDA, M&A), call `get_prediction_market` for what's priced.

   **Also call `get_issuer_credit` for $ARGUMENTS.symbol when the thesis touches financing** — a debt-funded buildout, a refinancing wall, a covenant test, heavy capex against negative FCF, or any name routed to the bearish framework. Credit usually reprices such a name before equity does, so its own bond spreads are a read the equity tape doesn't carry. Skip it for asset-light, net-cash names where there's nothing to find. Two ways to use the output:
   - **Level** — the issuer's median G-spread against its matched rating-cohort OAS says whether credit prices it consistent with, or materially worse than, its rating.
   - **Direction** — spreads wider than a prior reading while the equity is higher is the disconnect worth acting on. This is a row in the [bearish-framework.md](../../docs/bearish-framework.md) valuation-disconnect table.

   If the tool reports no priceable bonds, score it **n/a** rather than "no disconnect" — a company whose debt is all convertibles (IREN, NBIS) has no readable credit spread, which is a coverage gap, not a clean bill of health.

2. Cross-reference the market regime with the stock-level signals from Step 1. Note:
   - IV environment: Is IV Rank high (>50%, sell premium) or low (<30%, buy premium)?
   - **VRP** (`get_variance_risk_premium`): this is the *authoritative* vol-pricing read — IV against a forecast of forward realized vol. Ratio ≥1.30 rich / 1.10-1.30 modestly rich / 0.95-1.10 fair / <0.95 cheap.
   - IV-HV spread: the raw trailing spread, kept only as a cross-check. **Where IV-HV and VRP disagree, VRP wins** — IV-HV compares forward IV to *trailing* realized vol, so it misreads the window right after a vol spike. The VRP output flags the divergence explicitly when it exceeds 3 vol points.
   - If the VRP output carries the **⚠ up-move artifact** flag, treat any "cheap" reading as unproven — realized vol was inflated by a one-way rally that IV never prices.
   - Momentum: RSI, SMA alignment, 2-week price action.
   - Earnings proximity: How close is the next earnings date?
   - Liquidity: Liq rating 1-2 (tight, good) or 3-4 (wide, caution)?

3. **Valuation-regime adjustment.** Apply the ERP tier to the intent from Step 1:
   - **Generous / Fair**: no adjustment, intent stands.
   - **Tight**: no automatic adjustment; flag if $ARGUMENTS.symbol is a high-multiple name (P/E > sector average) — reduce concentration on entry.
   - **Compressed**: if intent is Accumulate, downshift to Enter at discount (prefer CSP over direct buy). If Directional leverage, prefer Defined-risk exposure.
   - **Compressed-Negative**: skip new Accumulate entirely. Speculative-growth gate routes to skip. Pre-existing positions: hold, but no new adds.

   Curve regime feeds Step 3 strategy weighting (Bear Steepener is hostile to long-duration multiples; Bear Flattener less so; Bull Steepener opens multiple-expansion room). Per [valuation-regime.md](../../docs/valuation-regime.md).

4. If there are signal conflicts, apply the priority hierarchy: fundamentals > IV environment > technicals.

## Step 3: Choose Strategy

Match intent + signals to strategy via the intent→strategy matrix in [decision-framework.md](../../docs/decision-framework.md) Step 3. Detailed mechanics live in [strategy-catalog.md](../../docs/strategy-catalog.md).

**VRP gates the credit-vs-debit choice** once intent is fixed. Intent decides *what* you're expressing; VRP decides whether you express it by selling or buying premium:

| VRP read | Effect on structure |
|---|---|
| **Rich** (≥1.30) | Prefer the credit form — CSP over direct buy, BPS over bull call spread, bear call spread over bear put spread |
| **Modestly rich** (1.10-1.30) | Default matrix stands; mild tilt to credit |
| **Fair** (0.95-1.10) | No vol edge — pick on directional/capital grounds alone, and don't pay up for a vol view you don't have |
| **Cheap** (<0.95) | Prefer the debit form — long call/put over spreads, straddle for a vol bet; selling premium here is underwriting below fair value |

VRP never overrides intent — a Cheap read on a highest-conviction name still means accumulate, just via shares or LEAPS rather than a CSP.

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
- **Next step**: hand off to **`/ta $ARGUMENTS.symbol`** for entry timing and price levels (default mode), or `/ta $ARGUMENTS.symbol strike <intent> <delta>` to anchor a CSP/CC/put strike at structure. Use the mode-specific variants when applicable: `/ta $ARGUMENTS.symbol tranches` for Accumulate scale-in levels, `/ta $ARGUMENTS.symbol ipo` for sub-12-months-public names, `/ta $ARGUMENTS.symbol roll <strike> <expiry>` for an existing short option. Skip `/ta` only when the strategy needs no price-structure read (e.g., "wait for post-earnings, re-run /analyze then").
