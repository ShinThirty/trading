# Covered Call Overlay Framework

Once you own shares, the covered call decision is its own framework. The [decision framework](decision-framework.md) answers "how do I get in?" — this doc answers "when and how do I sell calls against my holdings?"

The core tension: every covered call is a bet that the stock WON'T exceed the strike by expiry. If you're wrong, you left money on the table. If you're right, you collected free premium. The skill is knowing which regime you're in.

## CC Step 1: Determine CC Intent

CC intent is independent of entry intent. A stock you accumulated with highest conviction can later become a thesis exit. Intent can evolve.

| Intent | Goal | You're saying... |
|--------|------|-----------------|
| **Thesis exit** | Align exit timing with macro/sector/cycle thesis | "I want out by this date at this price" |
| **Income generation** | Recurring premium on range-bound or slow-growth names | "I'll collect rent while holding" |
| **Growth with income** | Premium income while maintaining partial upside on winners | "Still bullish but want to get paid while waiting" |
| **Orderly liquidation** | Exit a position efficiently with premium kicker | "I'm done with this name" |

## CC Step 2: When to Write

**Timing triggers:**
- **After accumulation is complete** — don't sell calls while still building a position. Finish buying first.
- **Post-earnings** — best CC window. Fundamentals are known, residual IV inflates premiums, no gap risk for 3 months.
- **IV Rank > 30%** — premiums worth the capped upside. Below 30%, you're giving away upside for pennies.
- **Thesis timeline becomes clear** — when you can articulate "I want out by [date]", that's a CC trigger.

**When NOT to write:**
- **Still accumulating** — competing with yourself. The CC caps the very upside you're buying into.
- **Pre-catalyst with bullish conviction** — earnings, product launch, macro shift. If you expect a pop, don't cap it.
- **IV Rank < 25%** — premiums too thin to justify capped upside. Exception: thesis exits where timeline matters more than premium.
- **Deep underwater (>20% below cost basis)** — you'd have to sell calls below cost to get meaningful premium. Wait for recovery or reassess the position entirely.
- **First 2 weeks after entry** — give the position time to breathe. Exception: buy-writes where the CC was always part of the plan.

## CC Step 3: Coverage Ratio

How many shares to cover determines how much upside you retain. This is the most underrated CC decision.

| Forward conviction | Coverage | Rationale |
|---|---|---|
| Exit / declining thesis | **100%** | Full exit intended — cap everything |
| Range-bound / neutral | **75-100%** | Income-focused, OK with full assignment |
| Still bullish, want income | **50-75%** | Uncovered shares ride freely |
| High conviction, expect breakout | **0-25%** or skip | Don't cap your winners |

**Rule of thumb:** If you'd be upset getting called away at the strike, you're covering too many shares.

**Reassess coverage at every roll.** The coverage ratio is not locked in from the initial write. At each roll decision, re-evaluate forward conviction at *today's price* — a stock that doubled since the original write may have shifted from "high conviction accumulate" to "still bullish but fully valued," which drops coverage from 75% to 25-50%. For multi-contract positions, this means you can **roll some and let others assign** — you don't have to make the same decision for every contract.

**Partial coverage is a feature, not indecision.** Keeping 15-30% of shares uncovered on growth names gives you:
- Upside participation if the stock rips
- Psychological comfort to hold the covered portion without second-guessing
- Flexibility to write additional CCs later if conviction changes

**CCs as emotional armor.** Beyond income and exit timing, CCs serve a critical psychological function: they make drawdowns survivable. The premium cushions the felt loss enough to prevent an emotional exit. For volatile positions where you intend to hold through a multi-month thesis, writing a CC at entry (or shortly after) isn't just about income — it's about ensuring you can stick to the plan.

## CC Step 4: Strike Selection

| CC Intent | Delta Target | Approx. % OTM | Rationale |
|-----------|-------------|---------------|-----------|
| **Thesis exit** | **N/A — your exit price** | Varies | The strike IS the exit — pick where you'd sell outright |
| **Income generation** | **15-20 delta** | ~10-15% OTM | ~80-85% chance of keeping shares, small steady premium |
| **Growth with income** | **25-30 delta** | ~8-12% OTM | Enough room for modest appreciation, decent premium |
| **Orderly liquidation** | **40-50 delta** | ATM to 5% OTM | You want assignment — maximize premium on the way out |

**Why delta, not % OTM:** A 10% OTM call on a low-IV stock has a very different probability of being hit than 10% OTM on a high-IV stock. Delta normalizes for volatility — a 20-delta call is a ~20% probability of assignment regardless of IV. Always check delta from the chain, not just distance from spot.

**Modifiers:**
- **Underwater position (cost > current price):** Default: don't sell calls below your cost basis — a CC that locks in a guaranteed loss is worse than no CC. **Exception:** If the stock is >30% underwater but the thesis is intact, sell CCs below cost basis on **25% of shares only**. This gives you premium to lower cost basis, and if the 25% gets called away at a loss, you harvest a tax loss to offset winners while keeping 75% uncovered for recovery. Wash sale caution: don't buy more shares or sell CSPs on the same name within 30 days of the loss, or the deduction is disallowed.
- **Post-earnings:** Strike can be tighter (closer to ATM) — event risk is gone, fundamentals are known, less chance of a gap.
- **Pre-earnings:** Sell THROUGH earnings to capture elevated IV — crush works in the CC seller's favor. Or wait until after. Never sell a pre-earnings expiry with a tight strike — gap risk.
- **Technical resistance:** If the stock has a clear ceiling (e.g., prior high, round number), use it as a natural strike.

## CC Step 5: Expiry Selection

| CC Intent | Expiry | Rationale |
|-----------|--------|-----------|
| **Thesis exit** | **Match thesis timeline** | Expiry IS the exit schedule. |
| **Income generation** | **30-45 DTE, rolling** | Theta decay sweet spot. Roll at 50% profit or 14 DTE remaining. |
| **Growth with income** | **45-90 DTE** | Longer than pure income — fewer rolls, more premium per cycle. |
| **Orderly liquidation** | **30-60 DTE** | Near-term, get it done in one cycle. |

**Earnings interaction:**

| Earnings timing | CC expiry rule |
|----------------|----------------|
| Earnings within 2 weeks | **Wait** — don't write before a potential gap up |
| Earnings 3-6 weeks away | Sell THROUGH earnings if income intent (capture IV premium) |
| Earnings just passed | **Best window** — write immediately. Known fundamentals + residual IV |

## CC Step 6: Management

| Situation | Action |
|-----------|--------|
| CC at **50% profit** (income intent) | Buy back, reassess, write next cycle |
| CC at **80%+ profit** (any intent) | Buy back — remaining premium isn't worth the risk of reversal |
| Stock **approaching strike** (income/growth) | Roll up and out for credit if still bullish. Let assign if neutral. |
| Stock **approaching strike** (thesis exit) | **Let it happen.** The strike was your target. Don't roll. |
| Stock **drops significantly** after writing | CC is winning. Buy back at 80%+ profit, reassess thesis before writing another at lower strike. |
| **Earnings approaching** with short-term CC | Buy back if <50% profit realized — gap risk isn't worth remaining premium |
| **Ex-dividend approaching** with ITM CC | Buy back or roll if the call's extrinsic value < dividend amount — early assignment is likely (see below) |
| **Thesis changes** fundamentally | Roll strike/expiry to match new thesis, or buy back entirely to remove the cap |

**Ex-dividend early assignment:** If your short call is ITM heading into an ex-dividend date, market makers will exercise early when the call's remaining extrinsic value is less than the dividend amount. Check `get_dividend_history` for upcoming ex-dates and buy back or roll ITM calls before ex-date if extrinsic < dividend.

**The cardinal sin: thesis drift disguised as conviction.**

Rolling a thesis-exit CC further out because the stock is doing well is not disciplined — it's FOMO. If your thesis said "exit by Dec 2026," don't roll to Jun 2027 because the stock pumped. You need a genuine NEW reason to stay (new product cycle, new market, changed competitive landscape), not just "it's going up."

The one valid exception: when your fundamental thesis has genuinely evolved — a new product cycle, changed competitive landscape, or strengthened macro thesis. A single good earnings report or a day's rally is not a thesis change — it's a data point confirming the existing thesis is working, which means the CC is doing exactly what it was designed to do.

**Practical test:** Before rolling a thesis-exit CC, ask: "Would I buy this stock at today's price with the same position size?" If the answer isn't an enthusiastic yes, let the CC do its job.

## CC Step 6b: Roll Mechanics

Rolling is a tool, not a reflex. Before looking at roll economics, ask: **should this CC still exist?**

| Situation | Right move | Wrong move |
|-----------|-----------|------------|
| Thesis exit, stock approaching strike | **Let assign** — the strike was your exit price | Rolling because "it's going up" (thesis drift) |
| Growth with income, stock approaching strike | **Roll up and out** — you want to keep the position | Letting assign when you still want the shares |
| Thesis broken, stock falling | **Buy back CC, sell shares** — exit the whole position | Rolling down to a lower strike on a broken thesis |
| Income/wheel, stock falling | **Roll down for credit** — reset the wheel at a lower strike | Holding a high strike that earns no premium |

**When to roll (direction):**
- **Roll up** when stock is rising and you want to keep the position (growth with income intent)
- **Roll down** when stock has fallen and you want to reset premium income (income/wheel intent)
- **Roll out** (same strike, later expiry) when you want more time for the thesis to play out
- **Diagonal roll** (up + out) is the most common — gives both more upside room and more time

**Roll timing — the credit sweet spot:**
The best roll credits happen when the stock is **near the current strike**. ATM options have the highest extrinsic (time) value, so the old CC is expensive to buy back — but the new CC at a higher strike and later expiry is even more expensive because of the additional time. The net difference is your credit.

If the stock is far below the strike, both the old and new CC are cheap OTM options — rolling from one cheap option to another produces a small credit. Don't wait for the stock to fall away from the strike before rolling; the economics get worse.

**Roll timing — when during a rally:**

| Signal | Action | Why |
|--------|--------|-----|
| **CC delta reaches ~75-80** | Start evaluating rolls now | Beyond 80 delta, intrinsic grows faster than extrinsic — the roll economics deteriorate rapidly. At 90+ delta you're mostly buying back intrinsic. |
| **IV Rank elevated** (>30%) | Roll now — the new leg is richer | Elevated IV inflates the new CC's premium, which offsets or reduces the debit. After the spike collapses, that cushion disappears. |
| **Stock just gapped up** (>3% single day) | Wait 1-2 days | Bid/ask spreads on the current leg are inflated by short-term vol. Let the spread normalize before paying the close cost. |
| **Sustained rally** (>15% in 2 weeks, CC >10% ITM) | Roll on the next flat or red day | Don't wait for a multi-day pullback that may never come. In a momentum regime, spreads normalize intraday on any pause. Perpetually waiting means the CC goes deeper ITM and the debit grows. |
| **Gradual grind higher** (no gap) | Roll when ready | No spread distortion — execute at your discretion. |

**Roll rules:**
- **Roll for a credit when possible.** If the roll requires a debit, run the debit budget analysis before proceeding — see below.
- **Roll before earnings** if the CC goes through an earnings date and you expect a beat. After a gap up, the cost to close spikes and the roll credit shrinks or becomes a debit.
- **Roll to a thesis-aligned expiry.** A roll that extends past your thesis end date is not a roll — it's a new position. Apply the practical test.
- **Use `analyze_roll` to compare scenarios.** Check 2-3 strike targets and pick the one that balances credit received vs upside room. Pass `chain_credits` (from `get_cc_chain_pnl`) to get automatic debit budget verdicts.

**Debit roll rules (applies to both CCs and CSPs):**

A debit roll pays to avoid assignment. The question is whether the cost is justified. Three gates, all must pass:

| Gate | Check | Tool |
|------|-------|------|
| **1. Chain budget** | Debit ≤ 50% of accumulated chain credits. You're spending earned premium, not new capital. | `get_cc_chain_pnl` → pass as `chain_credits` to `analyze_roll` |
| **2. vs Assignment** | Debit < intrinsic value lost at assignment (stock price − CC strike for calls, put strike − stock price for CSPs). If the debit costs more than assignment, let assign. | Computed automatically by `analyze_roll` |
| **3. Thesis check** | "Would I buy this stock at today's price with the same size?" If not, the roll preserves a position you no longer want. | Manual judgment — the practical test |

If all three pass, the debit roll is a rational use of earned premium to preserve a wanted position. If any gate fails, let assign or accept the cap.

**Why 50% and not 100%?** Spending the entire chain budget on a single debit roll leaves nothing for future rolls or adverse moves. The 50% cap ensures you always retain a reserve.

## Chain P&L: The Hidden Cost of Rolling

**The 50% rule on a rolled position can be misleading.** "50% profit on the current leg" is not the same as "profitable chain." When you roll multiple times, you must track the **total chain credits** — the sum of all net credits received across every roll — not just the current leg's premium.

**Chain P&L rules (applies to both CCs and CSPs):**

1. **Track total chain credits** for every rolled position: sum of original premium + all net roll credits.
2. **Chain breakeven** = total chain credits. If the buyback exceeds this, the option chain lost money regardless of what the current leg shows.
3. **A losing CC chain is fine if shares won more.** The total covered position (shares + CC chain) is what matters. Rolling up means you chose share upside over CC profit — that's intentional, not a mistake.
4. **A losing CSP chain is a warning.** Rolling a CSP down repeatedly means the stock kept falling through your strikes. If the total chain credits are less than the final buyback cost, you paid more to avoid assignment than you collected. Ask: would taking assignment at the original strike have been better?
5. **When the chain loss exceeds the benefit, stop rolling.** If the CC chain loss is larger than the additional upside room captured (stock didn't actually rally to justify the rolls), the rolls were a mistake. Let the next CC assign or buy back and reassess.

## CC Step 7: Interaction with Macro Thesis

When you have a sector-level thesis (like the semi cycle), covered calls become the execution mechanism for an orderly exit. The thesis sets the timeline, the CC enforces it.

**Key rules for thesis-driven CCs:**
- **Stagger expiries** across the thesis timeline — don't put everything in the same month
- **Don't roll past the thesis end date** — if AI capex peaks mid-2027, Jan 2027 is the latest CC expiry
- **Accept that some names will run past the strike** — that's the price of discipline. You can't time the exact top.
- **Redeploy proceeds into the next thesis** — when semis get called away, CSP into Phase 3 software/application winners

See [cycle-health-check.md](cycle-health-check.md) for leading indicators that signal the capex turn before earnings announcements, and the defensive playbook to execute when 2+ signals flash yellow.
