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

**Quick start:** Run `get_entry_signals` for all quantitative conviction inputs (ROE, D/E, revenue growth, margin trend, PEG, sizing tier) plus IV and momentum signals in one call. Moat and AI ROI require qualitative judgment — use `get_company_news` and `get_income_statement` for supporting evidence.

**Conviction inputs — what raises or lowers conviction:**

| Factor | High conviction | Low conviction |
|--------|----------------|----------------|
| **ROE** | >25% — elite capital efficiency. If D/E >3x, ROE is inflated by leverage — discount it. | <15% — mediocre returns don't justify premium P/E |
| **Moat** | Monopoly/deep switching costs | Commodity, crowded market, active disruption threat |
| **Growth durability** | Recurring revenue, expanding TAM, secular tailwinds | Cyclical, geopolitical-dependent, or AI-threatened |
| **AI ROI** (for software/adopter names) | AI features driving revenue growth *with stable or expanding margins* | AI spending growing revenue but compressing operating margins. Immediately drop to low conviction. |

The AI ROI filter distinguishes **Builders** (semis/infra — revenue booms now but carries cycle risk) from **Adopters** (software — must prove AI monetization without margin destruction).

Drawdown alone is not conviction — the business quality determines whether the drawdown is an opportunity or a warning.

| Conviction | Intent | Goal | You're saying... |
|-----------|--------|------|-----------------|
| **Highest** | **Accumulate** | Own shares, full upside participation | "I want to own this stock now" |
| **High** | **Enter at discount** | Own shares at lower cost basis, premium is bonus | "I want to own this stock cheaper" |
| **High, time-specific** | **Directional leverage** | Leveraged bet on a near-term move with defined cost | "This stock is moving in the next 2-6 weeks" |
| **Moderate** | **Defined-risk exposure** | Bullish participation with capped downside | "I like this thesis but want to limit what I can lose" |
| **Low / Neutral** | **Harvest premium** | Extract income from range-bound or elevated IV | "I don't want to own this, I want to sell its volatility" |
| **Direction-agnostic** | **Bet on volatility** | Profit from large moves regardless of direction | "Something big is coming, I don't know which way" |
| **Negative** | **Bearish** | Profit from decline | "This stock is going down" |
| **N/A (existing position)** | **Hedge** | Protect current holdings | "I own this and want downside protection" |

## Step 2: Read the Signals

**Quick start:** Run `get_entry_signals` for all stock-level signals (conviction, IV, momentum) and circuit breaker detection in one call. Run `get_market_regime` for market-level context. See [market-regime.md](market-regime.md) for how each regime label maps to strategy preferences. Supplement with `get_company_news` for headwinds and `get_expected_move` for vol bets.

Before any spread or roll, check liquidity via `get_iv_metrics` (Liq 1-2 = tight, Liq 3-4 = caution) and `get_option_chain` bid/ask spreads. Cross-check earnings dates from `get_iv_metrics` and `get_earnings_calendar`; if they disagree, use the later date.

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

Once intent is set and signals are collected, match to the right strategy. See [strategy-catalog.md](strategy-catalog.md) for detailed mechanics, decision matrices, strike selection, roll rules, and management for each intent.

**Quick reference — intent to default strategy:**

| Intent | Default strategy | IV-HV > 10% shift | IV-HV < 5% shift |
|--------|-----------------|-------------------|-------------------|
| **Accumulate** | Direct buy (tranches) or hybrid | More CSP in the mix | More direct buy |
| **Enter at discount** | CSP (30-45 DTE) | CSP (richer premium) | CSP (still works) |
| **Directional leverage** | Long call (40-60 delta) | Prefer CSP/BPS instead | Long call (sweet spot) |
| **Defined-risk exposure** | Bull put spread | BPS (sell rich premium) | Bull call spread (buy cheap) |
| **Harvest premium** | Iron condor | Iron condor (best window) | Skip or butterfly |
| **Bet on volatility** | Long straddle/strangle | Sell vol instead | Buy vol (sweet spot) |
| **Bearish** | Bear put spread | Bear call spread | Bear put spread |
| **Hedge** | Protective put / collar | Collar (sell rich calls) | Protective put |

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

## Step 5: Set Management Rules

### Accumulate / Enter at discount:
- **CSP:** Close at 50% profit. If assigned, evaluate covered call overlay (wheel).
- **Direct shares:** No hard stop losses on high-conviction entries. Scale-in T2 triggers at 5-8% drop from T1.
- **If approaching CSP expiry ITM:** Let assignment happen if thesis intact. Only roll if thesis deteriorated.
- **Reassess thesis** if position drops >15% from entry — check fundamentals, not just price.

### Directional leverage:
- **Long call:** Set profit target at entry (50-100% return on premium). Take profits, don't diamond-hand.
- **Call backspread:** Let ride if move is developing. Close if stock stalls — time decay on 2 long legs hurts.
- **Both:** Exit immediately if catalyst disappoints. Cut losses inside 14 DTE — theta acceleration destroys value.

### Defined-risk exposure:
- **BPS:** Close at 50% of max profit or when short leg reaches 80% profit.
- **Bull call spread:** Let ride toward expiry if directional thesis intact. Close if underlying breaks below support.
- **PMCC:** Manage short call — roll up and out if challenged. LEAPS is the anchor.

### Harvest premium:
- **Iron condor/butterfly:** Close at 50% of max profit. Adjust or close tested side if underlying approaches short strike.
- **Calendar:** Close when near-term option decays to target or IV differential narrows.

### Bearish:
- **Bear spreads:** Close at 50-75% of max profit. Don't hold to expiry hoping for max.
- **Long puts:** Set profit target (e.g. 100% return on premium). Time decay is working against you.

### All strategies:
- **Exit signal:** Thesis broken (not price action). Revenue deceleration, margin collapse, competitive disruption, management change.
- **Covered call overlay** once shares are held: see [covered-call-overlay.md](covered-call-overlay.md).

### Thesis Checkpoint: When a Position Drops >15%

Don't watch the ticker and feel pain. Run this checklist:

1. **Is the end customer still spending?** Check the demand environment upstream of your company. If the buyers of your company's products are still deploying capital, the thesis is intact.
2. **Is this company-specific or sector-wide?** Company-specific drawdowns need more scrutiny. Sector-wide drawdowns are *often* noise — but not always. A sector-wide drawdown can also be the beginning of a cycle turn. If the drawdown aligns with your exit thesis signals, it's not noise — it's the signal.
3. **Has the competitive moat actually narrowed?** Check for concrete evidence: lost customers, cancelled contracts, actual product displacement. A narrative shift in financial media is not the same as lost revenue.
4. **Is the thesis timeline still valid?** A 2-month drawdown inside an 18-month thesis is noise, not signal.
5. **Would I buy this at today's price if I had no position?** Strip away anchoring to your entry.

If all five pass → hold or add. If any fail → exit regardless of price.

### Selling Into Strength vs Selling Into Recovery

**The diagnostic test:** "Am I selling because I've won, or because I've survived?"

| | Selling into strength | Selling into recovery |
|---|---|---|
| Position P&L | Green or solidly profitable | Still red or barely recovered |
| Motivation | "I've hit my target" | "I can finally get out" |
| Emotion | Confidence, maybe mild FOMO | Relief, exhaustion |
| Usually right? | Yes — disciplined profit-taking | Usually wrong — you paid the emotional cost of the drawdown but captured none of the recovery |

**The rule:** If you survived the worst of a drawdown, a partial bounce should confirm the thesis, not trigger an exit. The crash is the tax. The recovery is the refund. Don't walk away before the refund arrives.
