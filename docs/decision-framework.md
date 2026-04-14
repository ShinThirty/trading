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

**Conviction inputs — what raises or lowers conviction:**

| Factor | High conviction | Low conviction |
|--------|----------------|----------------|
| **ROE** | >25% — elite capital efficiency (ADBE 62%). If D/E >3x, ROE is inflated by leverage — discount it (GDDY 384% ROE is buyback engineering, not profitability). | <15% — mediocre returns don't justify premium P/E |
| **Moat** | Monopoly/deep switching costs (ADBE creative suite) | Commodity, crowded market, active disruption threat |
| **Growth durability** | Recurring revenue, expanding TAM, secular tailwinds | Cyclical, geopolitical-dependent, or AI-threatened |
| **AI ROI** (for software/adopter names) | AI features driving revenue growth *with stable or expanding margins* — AI is monetized profitably (ADBE Firefly upsell) | AI spending is growing revenue but compressing operating margins — inference costs eating profits. Revenue growth without margin stability = burning cash to look like an AI company. Immediately drop to low conviction. |

The AI ROI filter distinguishes **Builders** (semis/infra — revenue booms now but carries cycle risk) from **Adopters** (software — must prove AI monetization without margin destruction). A software company showing AI-driven revenue growth but compressing margins is failing the adopter test. The question evolves from "when will they stop spending?" to "where are they spending, and is it actually working?"

A stock can have a 50% drawdown and still deserve low conviction if the ROE is mediocre and the moat is under attack (WDAY, NOW). Conversely, a 30% drawdown on a 62% ROE monopoly is high conviction (ADBE). Drawdown alone is not conviction — the business quality determines whether the drawdown is an opportunity or a warning.

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

**Quick start:** Run `get_market_regime` for a snapshot of volatility, trend, macro, and sector conditions before diving into individual signals. See [market-regime.md](market-regime.md) for how each regime label maps to strategy preferences.

Collect these inputs — which ones matter depends on intent:

| Signal | How to measure | Source | Used by |
|--------|---------------|--------|---------|
| **Drawdown** | % below 52-week high | `get_quote` (52W High) | Accumulate, Enter at discount |
| **Revenue growth** | YoY quarterly revenue growth % | `get_income_statement` | Conviction (Step 1), Sizing via PEG (Step 4) |
| **Operating margin** | Operating income / revenue, and trend | `get_income_statement` | Conviction — expanding margins = moat, compressing = red flag |
| **ROE** | Net income / shareholders' equity | `get_basic_financials` | Conviction (Step 1) |
| **P/E** | Price / TTM earnings | `get_basic_financials` | Sizing via PEG (Step 4) |
| **IV-HV spread** | IV 30d minus HV 30d | `get_iv_metrics` | All option strategies |
| **IV Rank** | Current IV vs 52-week IV range | `get_iv_metrics` | Premium selling strategies |
| **Earnings proximity** | Days to next report | `get_iv_metrics` (Earnings) | All strategies |
| **Momentum** | RSI (14-day): <30 oversold/falling, >70 overbought. SMA 50 vs 200 for trend. | `get_technical_indicators` | Accumulate, Enter at discount |
| **Headwinds** | Active stock-specific risk | `get_company_news` | All strategies |
| **Expected move** | ATM straddle price at target expiry | `get_expected_move` | Vol bets, premium harvesting |
| **Options liquidity** | Liquidity rating + bid/ask spread + open interest | `get_iv_metrics` (Liq 1-4) + `get_option_chain` | All option strategies |

**Revenue growth and operating margin must be pulled from `get_income_statement`, not estimated from memory or articles.** These feed directly into PEG sizing (Step 4) and conviction (Step 1). Compare at least 2 quarters to identify the trend — a single quarter can mislead.

**Options liquidity check before any spread or roll.** Before approving a spread, CSP, or roll, check the bid/ask spread and open interest on the target contracts via `get_option_chain`. Wide bid/ask spreads bleed out credit on rolls and spreads — if the spread is >10% of the contract price, the fill economics are poor. TastyTrade's liquidity rating (Liq 1-4 from `get_iv_metrics`) is a quick screen: Liq 1-2 = tight markets, Liq 3-4 = proceed with caution on multi-leg strategies.

**Earnings date cross-check.** The framework hinges on earnings timing ("always sell THROUGH the nearest earnings date"). Earnings dates from `get_iv_metrics` and `get_earnings_calendar` are estimates that can shift by a week. Before structuring a trade around an earnings date, cross-check both sources. If they disagree, use the later date to avoid expiring before the event.

### Signal Conflict Resolution

When signals conflict, **fundamentals override technicals, always.** Technicals tell you how much a stock moved; fundamentals tell you why. The "why" determines conviction; technicals only refine timing within an already-approved trade.

**Priority hierarchy:**
1. **Thesis / fundamentals** (conviction inputs, news, earnings, margins) — can kill a trade entirely
2. **IV environment** (IV rank, IV-HV) — determines strategy structure (buy vs sell premium)
3. **Technicals** (RSI, SMA) — timing refinement within an already-approved trade

**Circuit breakers for specific conflicts:**

**1. Value Trap (technicals bullish + fundamentals bearish)**

Signals: `get_technical_indicators` shows RSI <30 (oversold) at a historical support level. But `get_income_statement` shows operating margins compressing for 2+ quarters, or `get_company_news` flags a severe headwind (lost customer, regulatory action, competitive displacement).

Action: **Hard stop.** The stock is oversold for a reason — the business is deteriorating. Historical support is meaningless when the company is no longer the same company that established it. Drop to low conviction, reject Accumulate/Enter at discount.

**2. Price Dislocation (technicals bearish + fundamentals bullish)**

Signals: `get_technical_indicators` shows steep downtrend, below 200 SMA. But `get_income_statement` shows revenue growth accelerating and `get_basic_financials` confirms ROE >25%.

Action: **Proceed — this is what the framework was built for.** Flag as high-conviction Accumulate. The bearish technicals dictate *how* to enter: favor the Hybrid (CSP-heavy) approach from the drawdown matrix to capture rich IV premium while the stock finds its floor.

**3. FOMO Trap (technicals bullish + fundamentals overvalued)**

Signals: Stock breaking to all-time highs, RSI >70, strong momentum. But Step 4 sizing calculates PEG >3.0 — you're overpaying for growth.

Action: **Cap the size.** Allow the trade but force Reduced position size (1 contract / 50 shares) and limit to directional leverage (call spread) rather than full accumulation. Never full-size into a momentum chase.

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

Base sizing on **growth-adjusted valuation** (PEG) and **portfolio concentration**:

**How to calculate PEG:**
1. Pull `get_income_statement` — get the most recent quarter's revenue and the same quarter from the prior year.
2. Calculate YoY revenue growth: `(current_quarter - same_quarter_prior_year) / same_quarter_prior_year × 100`.
3. PEG = P/E (from `get_basic_financials`) ÷ YoY revenue growth %.
4. Use **revenue growth**, not earnings growth — earnings are volatile on high-growth names due to stock comp, one-time charges, and investment cycles. Revenue growth is the more stable signal.
5. If growth is negative or near-zero, PEG is meaningless — fall back to raw P/E sizing (P/E <15x Full, 15-25x Standard, >25x Reduced).
6. **Margin compression invalidates PEG.** If operating margins are shrinking quarter-over-quarter, PEG is unreliable — the company may be buying revenue growth through heavy spend while destroying profitability. When margins are compressing, fall back to raw P/E sizing regardless of PEG. Revenue growth without margin stability (or expansion) is not durable growth.

| PEG | Position size | Rationale |
|-----|--------------|-----------|
| <1.5 | **Full** (2 contracts / 200 shares) | Paying less than fair value for growth (ADBE PEG ~1.2) |
| 1.5-3.0 | **Standard** (1 contract / 100 shares) | Fair value for growth (NOW PEG ~2.4) |
| >3.0 | **Reduced** (1 contract or 50 shares) | Overpaying for growth (PLTR PEG ~6.7) |

**P/E hard cap:** Regardless of PEG, never full-size above 80x P/E — extreme multiples amplify downside on any growth deceleration.

**Additional sizing rules:**
- Never allocate >15% of portfolio to a single name at entry
- Always reserve cash for T2 scale-in (don't deploy 100% on T1)
- If running multiple CSPs, total collateral should not exceed 60% of cash account
- Spreads allow more positions — reallocate freed capital across pipeline names
- **Limit new entries to 5-7 names per month.** In March 2026, 18 names were bought in 10 days — the shotgun approach diluted conviction and made it impossible to size properly. Run each name through Steps 1-4 before adding the next.

**Size for the drawdown, not just the upside.** Before entering, ask: "If this drops 40% over 2 months, will the dollar loss force me to sell?" If yes, the position is too large. The ALAB lesson: a $182 entry on a volatile semi name should have been half-size or structured with a CC, because the eventual -45% drawdown created a $14K emotional breaking point that forced a thesis-correct exit. Size so that the worst-case drawdown is painful but survivable without triggering an emotional sell.

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
2. **Is this company-specific or sector-wide?** Company-specific drawdowns need more scrutiny. Sector-wide drawdowns are *often* noise — but not always. **A sector-wide drawdown is also exactly what the beginning of a cycle turn looks like.** If you are actively timing a macro thesis (e.g., semi cycle peaking mid-2027), ask: "Is this the cycle turn I've been expecting, or a temporary pullback?" Check: are hyperscaler capex guides being cut? Are neocloud earnings missing? Is GPU rental rate compression showing up in data? If the sector drawdown aligns with your exit thesis signals, it's not noise — it's the signal you've been waiting for.
3. **Has the competitive moat actually narrowed?** Check for concrete evidence: lost customers, cancelled contracts, actual product displacement by a competitor. A narrative shift in financial media is not the same as lost revenue. Narrative ≠ reality.
4. **Is the thesis timeline still valid?** A 2-month drawdown inside an 18-month thesis is noise, not signal. If the thesis hasn't had time to play out, price action alone isn't a reason to exit.
5. **Would I buy this at today's price if I had no position?** Strip away anchoring to your entry. If the thesis was buyable at $182, it's *more* buyable at $100. The only thing that changed is your P&L, not the company.

If all five pass → hold or add. If any fail → exit regardless of price.

**Example — ALAB (Apr 2026):** All five passed. Hyperscaler capex still growing, sector-wide drawdown (not ALAB-specific), no competitive moat change, thesis timeline intact (semi cycle through mid-2027), stock was cheaper by every metric. The exit at $125 was emotional, not analytical. Stock ripped 29% in the 4 days after selling.

**Example — CRDO (Mar 2026):** Arguably harder — had a specific narrative headwind ("optical replaces copper"). But all five still passed: customers still shipping AECs, Nvidia said "both copper AND optical," patent settlements proved the tech was valuable, semi cycle timeline intact. Held through -30%. Recovered +53% from the low. DustPhotonics acquisition later removed the narrative risk entirely.

### Selling Into Strength vs Selling Into Recovery

These look similar on a chart but are psychologically opposite:

**Selling into strength:** Your position is working. The stock is at or near highs, and you're taking profits because the price has reached a level where you're happy to sell. *You're selling because the stock went up.*

- LITE: Bought $650 → sold tranches at $692, $780, $790, $910. Each sell was higher than the last.
- XLE: Bought $56.60 → sold $60.30. Clean exit at a profit target.

**Selling into recovery:** Your position was deeply underwater. The stock bounced partially, and you sell because the bounce gave you a "chance to get out" — not because you've reached a profit target. *You're selling because the stock stopped going down.*

- ALAB: Bought $182 → ground to $100 (-45%) → bounced to $129 → sold. The recovery brought relief, not confidence. The sell was about exhaustion, not analysis.

**The diagnostic test:** "Am I selling because I've won, or because I've survived?"

| | Selling into strength | Selling into recovery |
|---|---|---|
| Position P&L | Green or solidly profitable | Still red or barely recovered |
| Motivation | "I've hit my target" | "I can finally get out" |
| Emotion | Confidence, maybe mild FOMO | Relief, exhaustion |
| Usually right? | Yes — disciplined profit-taking | Usually wrong — you paid the full emotional cost of the drawdown but captured none of the recovery |

**The rule:** If you held from $182 to $100 and survived the worst, a bounce to $129 should confirm the thesis, not trigger an exit. The crash is the tax. The recovery is the refund. Selling into a recovery is paying the tax and walking away before the refund arrives.
