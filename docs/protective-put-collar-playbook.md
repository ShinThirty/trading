# Protective Put & Collar Playbook

Once you own shares, the hedge decision is its own framework. The [decision framework](decision-framework.md) answers "how do I get in?", [covered-call-overlay.md](covered-call-overlay.md) answers "when do I sell calls?", and this doc answers "when and how do I buy puts on a position I own?"

**Scope:** Single-name (and ETF) protective puts and collars. **Not in scope:** the portfolio-level structural tail program (SPY puts, 20-25% OTM, 90-120 DTE) — that lives in [tail-hedge-playbook.md](tail-hedge-playbook.md) and operates on different rules.

The core tension: every protective put is an admission that either (a) the threat is real enough to insure against, or (b) the position is sized larger than your real tolerance. Most of the time, the cheaper answer is to trim — but tax, thesis, or timing constraints occasionally make the put the right call. The skill is knowing which case you're in before you pay the premium.

## The cheapest hedge is sizing

Before reaching for any put, run this gate. The protective put is a paid solution to a problem you may already be able to solve for free.

| Question | If yes... | If no... |
|----------|-----------|----------|
| Is the position over my sizing cap (>15% portfolio)? | **Trim first.** Bringing size back to plan is free; a put costs premium. | Continue to next gate. |
| Would I buy this stock at today's price with the same size? | Continue to next gate. | **Sell, don't hedge.** A put on a position you wouldn't reopen is insurance on a house you should be selling. |
| Can I just absorb the worst-case drawdown without forced selling? | **Skip the hedge.** Sizing already IS the hedge. | Continue to next gate. |
| Is there a tax / wash-sale / lockup / thesis-timing reason I can't trim now? | **Hedge is on the table.** Proceed to Step 1. | **Trim instead.** Cheaper, simpler, fewer moving parts. |

The structural tail hedge already insures the portfolio against systemic crashes — protective puts add **idiosyncratic** protection (this name, this catalyst, this window). Don't double-hedge the same risk.

## Hedge Step 1: Determine Hedge Intent

Intent is independent of entry intent. The same stock can be hedged for different reasons across its life. Pick one — they have different strike/expiry/management rules.

| Intent | Goal | You're saying... |
|--------|------|-----------------|
| **Event hedge** | Insure against a known, bounded catalyst | "Earnings / FDA / decision is X days away — I need protection through it" |
| **Profit lock** | Preserve unrealized gains on a winner without selling | "I won't sell (tax / thesis intact), but I can't watch this give back 30%" |
| **Conviction wobble** | Hold through volatility without panic-selling | "Thesis is intact but I'm nervous — the put lets me sleep" |
| **Concentration hedge** | Insure a position that grew past sizing limits | "Position is too large but trimming it costs taxes / breaks thesis" |
| **Macro overhang on a single name** | Insure a specific name against a sector/macro tail | "I like the company but this sector is one headline from a -25% repricing" |

If you can't articulate the intent in one sentence, you're hedging anxiety — that's almost never a trade. Either size down or hold.

## Hedge Step 2: When to Buy

**Timing triggers:**
- **Catalyst date is set** — earnings, FDA decision, macro print, lockup expiry. The threat window is bounded; the put has a job.
- **Position appreciated >50% from entry** — profit-lock candidate. Larger absolute dollars at risk = larger absolute dollars worth insuring.
- **IV Rank < 30%** — puts are cheap. Best window for opening profit-lock / conviction-wobble / macro hedges (the ones without a hard deadline).
- **Macro regime turned defensive** — Bear regime score moves Watchful → Building (see [bear-regime-playbook.md](bear-regime-playbook.md)) and you can't trim concentrated names.

**When NOT to buy:**
- **IV Rank > 70% with no specific catalyst** — you're buying insurance at peak prices for an unknown threat. Wait or use a collar (the sold call funds the put).
- **Thesis is broken** — exit the shares. A put on a broken thesis bleeds premium while delaying the inevitable sale.
- **Position is small enough to absorb worst-case drawdown** — sizing IS the hedge.
- **Generic "market feels frothy" anxiety** — that's the [structural tail program's](tail-hedge-playbook.md) job. Single-name puts for systemic risk just stack drag on top of drag.
- **Within 14 DTE of expiry with no catalyst inside the window** — theta acceleration eats the put before it can do anything.

## Hedge Step 3: Coverage Ratio

How many shares to hedge. The default is **not** 100% — that's expensive and often unnecessary.

| Intent | Coverage | Rationale |
|--------|----------|-----------|
| **Event hedge** (binary, large gap risk) | **50-100%** | Full coverage if the gap could be career-ending; partial if you'd accept a -15% gap as a buying opportunity |
| **Profit lock** | **50-75%** | Hedge the gains you can't afford to give back; let the rest ride. Full coverage caps participation in any continuation rally. |
| **Conviction wobble** | **25-50%** | The put is psychological insurance, not full protection. Smaller coverage keeps the premium drag tolerable. |
| **Concentration hedge** | **Coverage on the excess only** | If position is 22% of portfolio and your cap is 15%, hedge the 7% of excess shares — not the whole position. |
| **Macro overhang** | **25-50%** | The risk is real but probabilistic. Partial coverage matches partial probability. |

**Rule of thumb:** If the put expiring worthless would feel like a wasted insurance premium, you bought too much coverage. If a -30% move would still hurt despite the hedge, you bought too little.

**Partial coverage is a feature, not indecision.** Hedging 50% of the shares means: the protected half lets you hold through a real drawdown, the uncovered half keeps you honest about the cost of the program.

## Hedge Step 4: Strike Selection

Strike defines what you're actually insuring against. Like covered calls, prefer **delta** over % OTM — delta normalizes across IV.

| Intent | Delta target | Approx. % OTM | Rationale |
|--------|-------------|---------------|-----------|
| **Event hedge** (binary gap) | **30-40 delta** | 3-7% OTM | Tight enough to engage on the gap. Pay for it — the event is *why* you bought the put. |
| **Profit lock** | **20-30 delta** | 7-12% OTM | Lock in a defined floor. You accept a "deductible" before insurance kicks in. |
| **Conviction wobble** | **15-25 delta** | 10-15% OTM | Insurance against a panic-sell, not against every wiggle. Cheaper premium, higher strike pain. |
| **Concentration hedge** | **20-30 delta** | 7-12% OTM | Treat the excess shares like a tail bet — you'd be OK seeing the broader position trim itself via assignment of an offsetting CC at this level. |
| **Macro overhang** | **15-20 delta** | 12-20% OTM | You're insuring against a sector-wide repricing, not normal vol. Deeper OTM, cheaper drag. |

**Why not ATM puts?** ATM puts are the most expensive per dollar of strike protection and decay the fastest. Reserve them for binary event hedges where you genuinely expect the put to go ITM, not for ongoing insurance.

**Modifiers:**
- **Pre-earnings:** IV is inflated. Either go further OTM (cheaper at high IV) or switch to a collar (sold call recoups some of the inflated put cost).
- **Post-event drop already happened:** Don't buy puts after the gap — you missed the move and IV crushed. Re-evaluate the underlying thesis instead.
- **Liquidity check:** Run `get_iv_metrics` for the Liquidity rating. Liq ≤ 2 means spreads will eat 5-10% of the put's value on entry alone — go to a more liquid expiry or use a collar (the spread cost is split across two legs).
- **Skew warning:** OTM puts typically carry 5-15 IV points more than ATM (the put skew). Deep OTM strikes look cheap in dollars but expensive in IV. This is the cost of crash insurance — accept it for tail-only intents, avoid it for bounded event hedges where you can buy closer to ATM.

## Hedge Step 5: Expiry Selection

Match the expiry to the **threat window**, not to a default DTE.

| Intent | Expiry | Rationale |
|--------|--------|-----------|
| **Event hedge** | **Catalyst + 7-14 days buffer** | Covers the event itself plus a few days of post-event follow-through. Don't pick a pre-event expiry that wastes the put. |
| **Profit lock** | **60-120 DTE, rolling** | Long enough that theta isn't punishing; short enough that you reassess regularly. |
| **Conviction wobble** | **30-60 DTE** | The wobble is short-term by definition. If it lasts longer, the position is wrong-sized. |
| **Concentration hedge** | **90-180 DTE** | Lower $/day theta cost, less management. Treat the cost like a multi-month sizing accommodation. |
| **Macro overhang** | **90-120 DTE** | Match the typical macro thesis cycle. Roll if the overhang persists; close if it resolves. |

**Earnings interaction:**

| Earnings timing | Protective put expiry rule |
|----------------|---------------------------|
| Earnings within 7 days | **Sell THROUGH earnings** if hedging is the intent — IV peak is part of the price |
| Earnings 2-6 weeks away (non-earnings hedge) | **Sell pre-earnings** if the threat is unrelated to earnings (e.g., macro) — avoid paying the earnings IV premium for unrelated protection |
| Earnings just passed | **Best window for non-event hedges** — IV crushed, theta resumed, clean runway |

**Don't pick an expiry past your intended hold period.** If you'd sell the shares in 3 months on thesis, don't buy a 6-month put. The right answer is "sell shares + buy short-dated put for the bridge," not "long put as a permanent shadow."

## Hedge Step 6: Management

| Situation | Action |
|-----------|--------|
| Threat passed (event resolved, macro cleared, IV normalized) | **Close the put** — reclaim remaining premium. Don't let inertia decay it to zero. |
| Threat extended (catalyst pushed back, macro overhang persists) | **Roll out** if the new expiry still has a clear deadline. If the deadline keeps slipping, the position is wrong-sized — trim shares instead. |
| Put goes ITM (you were right about the move) | **Take profit at 100-200%** — the put did its job. Reassess: hold shares + buy fresh OTM put, or sell shares now. Don't ride an ITM put indefinitely; you're now long volatility. |
| Stock rallies, put bleeds | **Hold to threat resolution OR close if intent expired.** Conviction-wobble hedges close when conviction returns. Event hedges close after the event regardless of P&L. |
| Stock approaching put strike (put gaining value) | **Don't sell the put** — it's about to do its job. Sell shares if you've decided the thesis is broken; otherwise let the put protect. |
| Thesis broken while hedge is active | **Sell shares first, then close put.** The put may be near-the-money and valuable — sequencing matters. |
| 21 DTE remaining, threat unresolved | **Roll** or close + re-open at the right expiry. Don't ride theta acceleration. |

**The cardinal sin: rolling a protective put as a habit.**

Each roll should answer: *is the threat still real?* If yes, roll. If no, close. Auto-rolling protective puts means you've turned hedging into a position — that's the start of a tail-hedge program (which has its own playbook) or a covert "I want to be short this name" position (which should be a real short, not insurance drag).

**Re-evaluate every 2 weeks.** Calendar it. Hedges decay silently; sizing creep, thesis evolution, and IV environment shifts all change the right answer.

**The honest test:** Before holding a put past its original threat window, ask: *would I open this hedge today at today's premium?* If no, close it.

## Hedge Step 7: When to Use a Collar Instead

A **collar** is a protective put + a covered call on the same shares. The sold call funds (partially or fully) the protective put. Three structures:

| Structure | Construction | When to use |
|-----------|-------------|-------------|
| **Net-debit collar** | Put cost > call premium | Want strong downside protection, accept small drag, willing to cap upside |
| **Zero-cost collar** | Put cost ≈ call premium | The classic structure — strikes chosen so net cost ≈ $0 |
| **Net-credit collar** | Put cost < call premium | High IV environment, the sold call overfunds the put — you get paid to hedge |

**When a collar beats a naked protective put:**

| Condition | Why collar wins |
|-----------|----------------|
| **IV Rank > 50%** | Sold call premium is rich; offsets inflated put cost. Both legs benefit from the same elevated IV. |
| **You already had a CC in mind** | Adding a put converts the CC overlay into a collar — same upside cap, plus downside protection. |
| **Pre-earnings hedge** | Both legs are inflated equally — the credit from the call materially offsets the put cost. |
| **Position has hit profit target but you don't want to sell** | The CC strike becomes your exit price; the put protects gains until then. Both purposes served. |
| **Concentration hedge on a name you'd be OK trimming** | The CC assignment trims the position naturally; the put insures while you wait. |

**When NOT to collar:**

| Condition | Why naked put wins |
|-----------|-------------------|
| **High forward conviction (still bullish)** | Don't cap upside on a name you expect to break out — the CC leg becomes the cardinal sin from [covered-call-overlay.md](covered-call-overlay.md). |
| **IV Rank < 30%** | Both legs are cheap. The call premium doesn't materially fund the put. Skip the cap. |
| **Range-bound stock, no catalyst** | The put may never matter; you're just selling upside for nothing. |
| **Single binary event you expect to win** | Don't cap upside into the event you're bullish on — the put alone is the right tool. |

### Collar strike selection

The two strikes define the **active zone** where the position participates in moves. Wider zone = more participation, more debit. Narrower zone = less participation, cheaper or net-credit.

| Component | Strike target | Rationale |
|-----------|--------------|-----------|
| **Put strike** | **5-12% OTM** | Your hedge floor. Same selection logic as standalone protective put (Step 4). |
| **Call strike** | **8-15% OTM** (or your thesis exit price) | Your upside cap. Same logic as covered-call-overlay.md Step 4 — pick the price you'd sell outright. |

**Zero-cost collar math:** The strikes that produce zero net cost depend on IV skew. In normal markets, the put strike sits ~3-5% closer to spot than the call strike (because OTM puts carry higher IV than equidistant OTM calls). This is a feature: you give up less upside than you protect downside.

**Don't force zero-cost.** If the "zero-cost" strikes leave the put strike too close to spot (you're paying very little protection) or the call strike too close to spot (you cap upside aggressively), pay the small debit for better strikes. The right collar is rarely exactly zero-cost.

### Collar duration

| Collar intent | Duration | Rationale |
|--------------|----------|-----------|
| **Event collar** | Match the event window + 1-2 weeks (single expiry both legs) | Both legs expire together; clean exit. |
| **Profit-lock collar** | **30-60 DTE rolling** | Treat the CC leg per covered-call-overlay.md duration rules. Match the put expiry to the CC. |
| **Concentration collar** | **45-90 DTE** | Rolling cycle that mirrors a wheel — assignment of CC trims the position naturally. |

Always use the **same expiry for both legs**. Mismatched expiries (sometimes called "diagonal collars") are not collars — they're calendar spreads with a stock position. Different risk profile, different doc.

### Collar management

The collar is two positions sharing a single intent. Manage each leg per its own rules, but **always check both before acting on one**:

| Situation | Action |
|-----------|--------|
| Stock rallies toward call strike | **Roll the call leg per covered-call-overlay.md**, or let assign if at thesis exit. The put bleeds — leave it; it served as cheap insurance during the rally. |
| Stock falls toward put strike | **Hold both legs.** The put is doing its job; the call is decaying favorably. Don't roll the put down on a falling stock — that locks in a loss and converts insurance into a directional bet. |
| Stock at midpoint, both legs OTM, 21 DTE | **Roll the whole collar** (close both, reopen at new strikes/expiry) if the hedge intent is intact. Close both if the intent expired. |
| Earnings inside the collar window | **Hold through.** Both legs benefit from IV crush post-event — net P&L typically improves regardless of direction (within the active zone). |
| Thesis broken | **Close put first, then call (or unwind together), then sell shares.** Sequencing matters when both legs have value. |

**Cardinal sin in collars:** rolling the call up after a rally "to keep more upside" while leaving the put unchanged. That converts the collar into a directional bet — you're now long shares + long stale put, with no upside cap *and* a decaying drag. If the rally invalidates the original hedge intent, close the whole collar and reassess as a normal CC decision.

## Interaction with the structural tail hedge

The single-name protective put / collar and the [structural tail program](tail-hedge-playbook.md) are complementary, not redundant:

| Risk type | Insured by |
|-----------|-----------|
| **Systemic crash** (-15%+ in SPY) | Structural tail program (SPY 20-25% OTM, 90-120 DTE) |
| **Idiosyncratic gap** (earnings, FDA, fraud, single-name news) | Single-name protective put |
| **Sector repricing** (broader than one name, narrower than SPX) | Either — prefer single-name puts on the 1-2 biggest exposures rather than buying a sector ETF put |
| **Concentration above sizing cap** | Trim first; single-name put on residual excess if trim is blocked |

**Don't double-hedge the same risk.** If the structural SPY tail is on and a single-name macro hedge would essentially insure the same beta, the SPY hedge is already doing the job. Reserve single-name puts for risks the index hedge doesn't capture (binary catalysts, name-specific gap risk, alpha-driven exposures uncorrelated to SPX).

## Common mistakes

1. **Buying puts to manage anxiety, not risk.** If you can't articulate the threat in one sentence, you're paying premium to feel better. Size down instead.
2. **Hedging a broken thesis.** The put delays the sale and adds cost. Sell the shares.
3. **Holding the put past the threat window.** Inertia is expensive. Close when the intent expires, regardless of P&L.
4. **Buying ATM puts when OTM would do.** ATM puts are insurance with no deductible — and a premium that reflects it. Use them only when you genuinely expect the put to go ITM.
5. **Buying puts pre-event without considering the collar.** When IV is inflated, the sold call materially funds the put. The collar costs much less and you've already capped upside on a name worth hedging.
6. **Stacking single-name puts on top of the structural SPY hedge for systemic risk.** Pick one. The index hedge is more capital-efficient for beta risk.
7. **Rolling protective puts as a habit.** Auto-rolling turns insurance into a position. If you want to be structurally short the name, be honest about it — that's a directional trade, not a hedge.
8. **Treating zero-cost collars as "free."** They cost upside, which is the most expensive currency on a high-conviction name. Use them when you'd be OK selling at the call strike anyway.

## References

- `get_iv_metrics` — IV Rank for entry timing + Liquidity rating before any leg
- `get_expected_move` — sizes the threat for event hedges
- `get_option_chain` — strike + delta + bid/ask for both legs
- `analyze_strategy` — collar P&L profile (max gain / max loss / breakevens)
- `analyze_roll` — for rolling either leg of a collar or a standalone put
- `preview_webull_order` — always preview multi-leg orders before placing
- [covered-call-overlay.md](covered-call-overlay.md) — companion doc; the CC leg of a collar follows its rules
- [tail-hedge-playbook.md](tail-hedge-playbook.md) — portfolio-level tail program (separate problem, separate rules)
- [management-rules.md](management-rules.md) — the brief Hedge section that pointed here
