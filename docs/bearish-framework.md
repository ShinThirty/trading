# Bearish Framework

Companion to [decision-framework.md](decision-framework.md) for bearish and volatility plays on fundamentally deteriorating companies. This framework activates when `get_entry_signals` scores conviction as **Negative** (2+ quantitative factors score Negative) — the deterioration itself becomes the trade thesis.

**Current scope:** L2-compatible strategies (long puts, straddles, strangles). Bear spreads and credit strategies will be added when L3 options are approved (target: 2027).

## When This Framework Applies

`get_entry_signals` auto-scores four quantitative factors (ROE, Growth, Margins, Cash Flow). When 2+ score Negative, conviction is Negative and the tool routes here. This framework then assesses whether the deterioration is **mispriced** — that's the second gate before a bearish trade is approved.

1. **Fundamental deterioration** — confirmed by the conviction scoring (2+ Negative factors)
2. **Valuation disconnect** — the market is pricing in a better outcome than fundamentals support

A stock with terrible fundamentals trading at 0.3x book is not a bearish trade — the market already knows. A stock with terrible fundamentals trading at 400x earnings on narrative is a bearish opportunity — the gap between story and reality is tradeable.

---

## Step 1: Bearish Conviction Assessment

### Deterioration Signals

Score each factor. **Three or more "deteriorating" signals** establish bearish conviction.

| Factor | Deteriorating | Stable / Neutral | Improving |
|--------|--------------|------------------|-----------|
| **Revenue trajectory** | Declining YoY or decelerating for 2+ quarters | Flat | Accelerating |
| **Gross margins** | Negative or compressing below breakeven | Stable above breakeven | Expanding |
| **Operating margins** | Widening losses or compressing from positive | Stable (even if negative) | Narrowing losses |
| **Balance sheet** | D/E >3x AND current ratio <1.0 | Manageable leverage | Deleveraging |
| **Cash burn** | Accelerating; <12 months runway without new financing | Sustainable | Generating free cash flow |
| **Competitive position** | Losing share, competitor products superior, customer churn | Holding | Gaining share |

### Valuation Disconnect Signals

The deterioration must be **mispriced** for a bearish trade to work. Score at least one:

| Signal | Threshold | What it means |
|--------|-----------|---------------|
| **P/E vs growth** | P/E >50x with negative or <5% growth | Market pricing growth that doesn't exist |
| **Price vs analyst targets** | Stock >50% above consensus target | Speculative premium over professional estimates |
| **Equity vs own credit** | `get_issuer_credit`: median G-spread ≥2x the matched rating-cohort OAS, **or** spreads wider than the prior reading while the equity is higher | Two markets on the same capital structure disagree, and the bond market is the one with a maturity date |
| **Narrative dependency** | Entire bull case rests on unmonetized future | Price supported by story, not revenue |
| **Insider selling** | Net insider selling >$10M in past 6 months | Insiders don't believe the story |
| **Speculative rally** | >20% rally in 2 weeks on no fundamental catalyst | Momentum/squeeze disconnected from reality |

**On the credit row.** Added because the analyst-target test failed on the 2026 neocloud cohort — all four names traded *below* consensus (targets are junk where sell-side coverage is thin or promotional), yet CRWV's own paper was at ~700bp, 2.4x the single-B index, while its equity ran +76% off the low. Where a thesis turns on financing, credit is the better disconnect measure and the convergence mechanism is mechanical rather than narrative: a maturity wall reprices at the market's spread whether or not sentiment agrees.

Three cautions:

- **Absence of the signal is not a pass.** The test only exists for issuers with straight bonds held by a fund in the SPDR panel. IREN and NBIS have *no* readable spread — their debt is entirely convertibles, whose price is equity-driven. Score the row "n/a", not "no disconnect".
- **The ratio runs high by construction.** These are nominal G-spreads on callable paper against option-adjusted index spreads. Compare to the *matched* cohort (a BBB- name against broad IG will look wide and isn't), and read the placement, not the basis points.
- **A wide spread that is already wide is not an edge.** If credit has fully repriced, a put buyer is betting on convergence, not discovery. The direction test — spread widening while equity rises — is the stronger form, and needs a prior reading to compare against, so pull it on a cadence rather than once.

### Bearish Conviction Levels

| Bearish Conviction | Deterioration Signals | Valuation Disconnect | Intent |
|--------------------|----------------------|---------------------|--------|
| **High** | 4+ factors deteriorating | 2+ disconnect signals | Directional bearish (long puts) |
| **Moderate** | 3 factors deteriorating | 1 disconnect signal | Volatility play (straddle/strangle) |
| **Low** | <3 factors deteriorating OR no disconnect | — | SKIP — not enough edge |

---

## Step 2: Bearish Signals & Timing

### Entry Timing

| Signal | Best Entry | Worst Entry |
|--------|-----------|-------------|
| **Post-rally** | After speculative bounce exhausts (RSI >70 + fading volume) | During the rally (fighting momentum) |
| **Pre-catalyst** | 2-4 weeks before earnings; buy puts through the event | Day before earnings (IV crush risk) |
| **Technical breakdown** | Price breaks below SMA(50) after failed rally attempt | While price is above all moving averages and accelerating |
| **IV environment** | IV Rank <30% (cheap puts) | IV Rank >70% (expensive puts — wait for L3 credit strategies) |

### Bearish Circuit Breakers

These conditions **block or modify** a bearish trade:

| Circuit Breaker | Condition | Action |
|----------------|-----------|--------|
| **Short Squeeze Risk** | Short interest >20% of float AND stock in strong uptrend | **Hard stop.** Squeeze risk overwhelms thesis. Wait for exhaustion. |
| **Restructuring Pivot** | New management, asset sales, or debt restructuring materially improving balance sheet | **Pause.** Turnaround may be real — wait 1-2 quarters for confirmation. |
| **Revenue Catalyst** | Legitimate new revenue stream announced with real bookings (not just R&D promise) | **Reassess.** If monetization is real, bearish thesis may be broken. |
| **Dead Cat Bounce** | Rally on no fundamental change + declining volume | **Proceed.** Rally provides better entry for puts. |
| **Meme / Gamma Squeeze** | Social media driven, extreme volume spike, options gamma ramp | **Wait.** Let the squeeze exhaust. Re-enter puts after peak and RSI rolls over. |

---

## Step 3: Strategy Selection (L2)

### Decision Matrix

| Bearish Conviction | IV Rank | Catalyst Timing | Strategy |
|--------------------|---------|----------------|----------|
| High | <30% | Earnings 2-6 weeks out | **Long put** — buy through earnings |
| High | <30% | No near-term catalyst | **Long put** — 45-60 DTE, directional |
| High | 30-70% | Any | **Reduced size long put** — IV is fair, not cheap |
| High | >70% | Any | **Wait.** Puts are expensive. (L3: bear call spread) |
| Moderate | <30% | Earnings 2-4 weeks out | **Long straddle** — bet on big move either way |
| Moderate | <30% | No catalyst | **Long strangle** — wider strikes, cheaper entry |
| Moderate | >30% | Any | **Wait** or skip. (L3: iron condor with bearish lean) |

### Long put mechanics

Delta -0.30 to -0.40 (high conviction → closer to ATM at -0.40, moderate → further OTM at -0.25 to -0.30). Expiry 45-60 DTE, or 2-4 weeks past the next catalyst. Never buy inside 14 DTE — theta destroys value before the thesis plays out.

### Straddle / strangle mechanics

Use when conviction is moderate — you expect a big move but acknowledge the stock could rip higher on narrative. Straddle = ATM strikes (higher cost, higher probability); strangle = 1 strike width OTM each side (lower cost, needs bigger move). Expiry 2-4 weeks past expected catalyst. **IV Rank must be <30%** — you're buying volatility, so buy it cheap.

---

## Step 4: Sizing

Bearish plays carry a natural advantage (max loss = premium paid) but markets have a long-term upward bias, so bearish plays fail more often than bullish ones. Size conservatively.

### Position Sizing Rules

| Rule | Limit |
|------|-------|
| Max single bearish position | 3% of portfolio (premium at risk) |
| Max total bearish allocation | 10% of portfolio across all bearish positions |
| Max concurrent bearish positions | 2-3 names |
| Sector concentration | No 2+ bearish positions in the same sector |

Before entering, answer: "If this put expires worthless, does the loss change how I trade next month?" If yes, the position is too large.

---

## Step 5: Management

### Profit Targets

| Strategy | Take Profit | Stretch Target |
|----------|------------|----------------|
| Long put | 50% return on premium | 100% return |
| Straddle | 30% return on total premium | 60% return |
| Strangle | 40% return on total premium | 80% return |

Take profits. Bearish plays are harder to hold psychologically — bounces will test you, and theta is always working against you.

### Time Decay Rules

- **Exit at 21 DTE** if the thesis hasn't played out — don't let theta eat your position
- **Roll to next expiry** only if: thesis is intact AND the stock hasn't rallied >10% from entry
- **Never hold through expiry** — close or roll by 14 DTE at the latest

### Thesis Validation Checkpoints

Check every 2 weeks (or at each earnings report):

1. **Are fundamentals still deteriorating?** If margins stabilize or revenue re-accelerates for 2 consecutive quarters, the thesis is broken — close.
2. **Has the valuation disconnect narrowed?** If the stock has dropped 20%+ from entry, the mispricing may be corrected — take profits.
3. **Has a restructuring catalyst appeared?** New management, strategic pivot, or meaningful asset sale can break the bearish case.
4. **Is the narrative cracking?** When sell-side downgrades pile on or media tone turns bearish, consensus is catching up — your edge is shrinking. Take profits before the trade gets crowded.

### Exit Rules

| Signal | Action |
|--------|--------|
| Profit target hit | Close position |
| Fundamentals stabilizing (2 consecutive quarters of margin improvement) | Close — thesis broken |
| Stock drops >30% from entry | Take at least half off — most of the move is captured |
| New financing/restructuring that materially improves balance sheet | Reassess — may need to close |
| 21 DTE reached without thesis playing out | Close or roll |

---

## L3 Expansion (2027+)

When L3 is approved, add to the decision matrix: bear put spread (default high conviction at IV Rank 30-70%), bear call spread (credit strategy at IV Rank >70%, replaces "wait"), put backspread (crash bet — see strategy-catalog.md Valley of Death warning), and bearish-lean iron condor (moderate conviction alternative to straddle when IV is rich).
