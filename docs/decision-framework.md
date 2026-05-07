# Post-Screening Decision Framework

Every trade comes down to three questions: **Which**, **When**, and **How**.

- **Which** — What to trade. Driven by screening, thesis, and conviction. This happens upstream of this framework.
- **When** — When to enter or exit. Driven by signals: drawdown, IV environment, earnings proximity, momentum, thesis timeline.
- **How** — What structure to use. Driven by intent and signals: CSP vs direct buy, covered call vs hold, spread vs outright.

The relative weight of each question shifts by intent:

| Intent | Which | When | How |
|--------|-------|------|-----|
| Accumulate / Enter at discount | **Heaviest** | Important | Follows from signals |
| Directional leverage | Heavy | **Critical** | Follows from IV |
| Harvest premium | Lightest | **Heaviest** | Important |
| Bearish | Heavy | Important | Follows from IV |
| Covered call overlay | N/A (already own) | **Critical** | Follows from CC intent |

Conviction determines intent. Intent determines which signals matter (when). Signals determine strategy (how). The thesis is the thread connecting all three — and the hardest discipline is knowing when the thesis has genuinely evolved vs when greed or fear is rewriting it.

---

After screening confirms (or rejects) a thesis, run through these steps in order.

## Step 1: Determine Intent

Conviction drives intent. Intent drives strategy. Decide intent FIRST — everything else follows.

**Quick start:** Run `get_entry_signals` for all quantitative conviction inputs (ROE, Growth, Margins, Cash Flow — auto-scored into Bullish/Moderate/Neutral/Negative) plus IV and momentum signals in one call. Moat and AI ROI require qualitative judgment — use `get_company_news` and `get_income_statement` for supporting evidence.

**Conviction inputs — what raises, lowers, or inverts conviction:**

`get_entry_signals` auto-scores the quantitative factors (ROE, Growth, Margins, Cash Flow) into four tiers: Bullish, Moderate, Neutral, Negative. Moat and AI ROI require qualitative judgment — use `get_company_news` and `get_income_statement` for supporting evidence. When 2+ factors score Negative, the tool routes to the bearish framework.

**Quantitative factors** (auto-scored by `get_entry_signals`):

| Factor | Bullish | Moderate | Neutral | Negative |
|--------|---------|----------|---------|----------|
| **ROE** | >25% (no leverage inflation) | 15-25% | <15% | <5%; or D/E >3x with negative earnings |
| **Growth** | Rev >10% YoY, margins not compressing | Rev 5-10% | Rev 0-5% | Rev declining YoY or margins compressing |
| **Margins** | Op margin >20% | 10-20% | 0-10% | <0% (operating at a loss) |
| **Cash Flow** | Positive FCF | — | Single negative FCF quarter | 2 consecutive negative FCF quarters (burning) |

If D/E >3x, ROE is leverage-inflated — capped at Neutral even if the raw number is high.

**Qualitative factors** (manual assessment):

| Factor | Bullish | Neutral | Negative |
|--------|---------|---------|----------|
| **Moat** | Monopoly/deep switching costs | Commodity, crowded market, active disruption threat | Actively losing share, competitor products displacing, customer churn |
| **AI ROI** (software/adopter names) | AI features driving revenue growth *with stable or expanding margins* | AI spending growing revenue but compressing operating margins. Immediately drop to low conviction. | Spending on unmonetized narrative (robotaxi, AI chips, etc.) with no revenue pathway — valuation rests entirely on story |

The AI ROI filter distinguishes **Builders** (semis/infra — revenue booms now but carries cycle risk) from **Adopters** (software — must prove AI monetization without margin destruction).

Drawdown alone is not conviction — the business quality determines whether the drawdown is an opportunity or a warning. Similarly, bad fundamentals alone are not bearish conviction — the deterioration must be *mispriced* for it to be a trade.

| Conviction | Intent | Goal | You're saying... |
|-----------|--------|------|-----------------|
| **Highest** | **Accumulate** | Own shares, full upside participation | "I want to own this stock now" |
| **High** | **Enter at discount** | Own shares at lower cost basis, premium is bonus | "I want to own this stock cheaper" |
| **High, time-specific** | **Directional leverage** | Leveraged bet on a near-term move with defined cost | "This stock is moving in the next 2-6 weeks" |
| **Moderate** | **Defined-risk exposure** | Bullish participation with capped downside | "I like this thesis but want to limit what I can lose" |
| **Speculative growth** | **Pre-profit hyper-growth** | Small position in a pre-profit IPO with proven unit economics | "Real revenue, GAAP losses, but unit economics that can compound" |
| **Low / Neutral** | **Harvest premium** | Extract income from range-bound or elevated IV | "I don't want to own this, I want to sell its volatility" |
| **Direction-agnostic** | **Bet on volatility** | Profit from large moves regardless of direction | "Something big is coming, I don't know which way" |
| **Negative** | **Bearish** | Profit from decline or volatility on a deteriorating business | "This business is getting worse and the market hasn't priced it" |
| **N/A (existing position)** | **Hedge** | Protect current holdings | "I own this and want downside protection" |

When 2+ conviction inputs score "negative," route to the [Bearish Framework](bearish-framework.md) for detailed deterioration scoring, valuation disconnect assessment, and L2 strategy selection. A bad business at a fair price is a skip; a bad business at a delusional price is a trade.

For **pre-profit IPO candidates** (real revenue, GAAP losses, narrative-heavy story), the standard conviction tiers don't apply cleanly — the Negative-margins-Negative-Cash-Flow scoring routes them to bearish, but the burn may be the *entry condition* not the bear case. Route to the [Pre-Profit Speculative-Growth Framework](pre-profit-growth-framework.md) for unit-economics gating, sizing, and re-evaluation cadence. Default verdict per the framework's bias-to-rejection: better to miss future winners than admit ambiguous-tier names that get sentiment runway but disappoint long-term.

## Step 2: Read the Signals

**Quick start:** Run `get_entry_signals` for all stock-level signals (conviction, IV, momentum) and circuit breaker detection in one call. Run `get_market_regime` for market-level context. See [market-regime.md](market-regime.md) for how each regime label maps to strategy preferences. Supplement with `get_company_news` for headwinds and `get_expected_move` for vol bets.

Before any spread or roll, check liquidity via `get_iv_metrics` (Liq 3-4 = tight, Liq 1-2 = caution) and `get_option_chain` bid/ask spreads. Cross-check earnings dates from `get_iv_metrics` and `get_earnings_calendar`; if they disagree, use the later date.

### Active Macro Overhangs

`get_market_regime` captures regime labels (volatility, trend, breadth, sectors) but not narrative overhangs that aren't yet in price — commodity divergences, geopolitical tail risks, framing flips, capex commitment cycles. **Always check memory for active macro themes before finalizing any recommendation.** Relevant files:

- `project_spy_reversal_playbook.md` — reversal checklist + commodity divergence (USO/VIX) + Iran/Hormuz baseline
- `project_semi_cycle_thesis.md` — AI capex phases + hyperscaler capex commitment tracker
- `project_uninversion_watch.md` — yield curve + Fed cuts
- `project_ai_commoditization.md` — LLM ceiling / model commoditization thesis

These overhangs shift **entry timing**, not thesis viability. A bullish stock-level setup against a market ignoring oil at $150 calls for staying CSP-heavy with strikes pushed deeper OTM — the thesis is right but a systemic derisk takes everything down regardless of fundamentals. Memory entries decay; verify timestamps before relying on specific data points (a capex print or VIX reading >2 weeks old has lost most of its predictive value — re-pull current data).

### Signal Conflict Resolution

When signals conflict, **fundamentals override technicals, always.** Technicals tell you how much a stock moved; fundamentals tell you why. The "why" determines conviction; technicals only refine timing within an already-approved trade.

**Priority hierarchy:**
1. **Thesis / fundamentals** (conviction inputs, news, earnings, margins) — can kill a trade entirely
2. **IV environment** (IV rank, IV-HV) — determines strategy structure (buy vs sell premium)
3. **Technicals** (RSI, SMA) — timing refinement within an already-approved trade

**Circuit breakers** (auto-detected by `get_entry_signals`):

| Conflict | Condition | Action |
|----------|-----------|--------|
| **Value Trap** | RSI <30 but margins compressing | **Hard stop.** Drop to low conviction. Oversold for a reason. |
| **Justified Rally** | RSI >70 but margins expanding | **Don't short.** Overbought is justified by improving fundamentals. Momentum has fundamental backing. |
| **Price Dislocation** | Downtrend but revenue accelerating + ROE >25% | **Proceed.** High-conviction Accumulate. Use Hybrid (CSP-heavy) entry. |
| **Deteriorating Rally** | Uptrend but revenue declining | **Bearish setup.** Technicals mask weakening fundamentals. Rally is on borrowed time. |
| **FOMO Trap** | ATH + RSI >70 but PEG >3.0 | **Cap the size.** Reduced tier only. Prefer call spread over accumulation. |
| **Capitulation Bargain** | Near 52W low + RSI <30 + PEG <1 + margins not compressing | **Genuine bargain.** Not a value trap — cheap valuation with intact margins. High-conviction accumulate. |
| **Front-Run Catalyst** | Stock rallied >8% in 2 weeks into catalyst + catalyst info already leaked | **Bullish: wait for post-catalyst reaction.** Overpaying on timing, not valuation. **Bearish: rally provides higher entry for puts/bear spreads** — the run-up is your opportunity, not a warning. |
| **Pre-Priced Selloff** | Stock dropped >8% in 2 weeks into catalyst + bad news already known | **Bearish: wait for post-catalyst reaction.** Downside may already be priced in. **Bullish: selloff provides cheaper entry for shares/CSPs** — the drop is your opportunity, not a warning. |

## Step 3: Choose Strategy

Once intent is set and signals are collected, match to the right strategy. See [strategy-catalog.md](strategy-catalog.md) for detailed mechanics, decision matrices, strike selection, roll rules, and management for each intent. For bearish intent, see [bearish-framework.md](bearish-framework.md) for the full L2 decision matrix, sizing, and management rules.

**Quick reference — intent to default strategy:**

| Intent | Default strategy | IV-HV > 10% shift | IV-HV < 5% shift |
|--------|-----------------|-------------------|-------------------|
| **Accumulate** | Direct buy (tranches) or hybrid | More CSP in the mix | More direct buy |
| **Enter at discount** | CSP (30-45 DTE) | CSP (richer premium) | CSP (still works) |
| **Directional leverage** | Long call (40-60 delta) | Bull call spread (reduce vega) | Long call (sweet spot) |
| **Defined-risk exposure** | Bull call spread | BPS (sell rich premium) | Bull call spread (sweet spot) |
| **Speculative growth** | Direct buy single tranche, 3-5% portfolio cap | Skip — IV too rich; wait for next 10-K | Direct buy or long call (IV Rank <40 only) |
| **Harvest premium** | Iron condor / wheel | Iron condor (best window) | Skip, butterfly, or wheel |
| **Bet on volatility** | Long straddle/strangle | Sell vol instead | Buy vol (sweet spot) |
| **Bearish (L2)** | Long put (IV Rank <30%) | Wait (puts expensive) | Long put (sweet spot) |
| **Bearish (L3)** | Bear spread (credit or debit per IV) | Bear call spread | Bear put spread |
| **Hedge** | Protective put / collar | Collar (sell rich calls) | Protective put |

For **portfolio-level tail-risk hedging** (deep OTM index puts as a structural program, not tactical correction protection), see [tail-hedge-playbook.md](tail-hedge-playbook.md).

**Cross-stock tiebreaker:** When multiple pipeline names share the same intent and conviction tier, compare premium efficiency at a standardized delta to decide who goes first when capital is limited.

- **Credit strategies** (CSPs, CCs): Run `compare_credit_efficiency`. Ranks by annualized yield (premium / capital at risk, annualized), cushion/yield (OTM distance per unit of yield), and liquidity cost (spread friction). Higher yield = richer; higher C/Y = more safety per return.
- **Debit strategies** (long calls, long puts): Run `compare_debit_efficiency`. Ranks by cost of exposure (premium / delta-adjusted notional, as %). Lower = cheaper leverage per dollar of directional bet.

## Step 4: Size the Position

Base sizing on **growth-adjusted valuation** (PEG) and **portfolio concentration**.

Run `get_entry_signals` or `get_conviction_metrics` — both compute PEG (revenue-based), drawdown %, operating margin trend, and position size tier. The tools handle all edge cases: margin compression fallback to raw P/E, negative/zero growth, and the 80x P/E hard cap.

**Additional sizing rules:**
- Never allocate >15% of portfolio to a single name at entry
- Always reserve cash for T2 scale-in (don't deploy 100% on T1)
- If running multiple CSPs, total collateral should not exceed 60% of cash account
- Spreads allow more positions — reallocate freed capital across pipeline names
- **Limit new entries to 5-7 names per month.** Run each name through Steps 1-4 before adding the next.

**Size for the drawdown, not just the upside.** Before entering, ask: "If this drops 40% over 2 months, will the dollar loss force me to sell?" If yes, the position is too large. Size so that the worst-case drawdown is painful but survivable without triggering an emotional sell.

## Step 5: Manage the Position

See [management-rules.md](management-rules.md) for per-intent profit targets, exit triggers, thesis checkpoints, and selling discipline. See [bearish-framework.md](bearish-framework.md) for bearish-specific management. See [covered-call-overlay.md](covered-call-overlay.md) for CC rolls and management.
