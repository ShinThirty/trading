# Tail Hedge Playbook

The [decision framework](decision-framework.md) covers position-level risk via sizing, intent, and conviction. This doc covers **portfolio-level tail-risk hedging** — buying deep OTM index puts to insure against true crashes (>15-20% drawdowns), not corrections.

This is a structural program, not a tactical trade. The discipline is buying when nothing is wrong and *not* selling when nothing is wrong — because the whole point is asymmetric payoff in the rare event you can't time.

## Philosophy

**What we hedge:** Crashes (-15% to -50%+ in weeks). Black-swan, unpredictable timing, catastrophic to a long-biased portfolio.

**What we DON'T hedge:** Corrections (-3% to -10%). These are absorbed by the portfolio. Trying to hedge them is expensive correction insurance, not tail protection.

**Why:**

1. **Crashes can't be timed.** They're triggered by liquidity events (Lehman), pandemics (COVID), wars, or surprise rate moves. None are visible in the regime data until they're already underway.
2. **Corrections are survivable.** A long-biased $1M+ portfolio can absorb a -10% drawdown without forced selling. -20%+ starts breaking position sizing math and forcing decisions.
3. **Insurance is asymmetric.** A 0.5-1% annual drag protects against a 30-50% portfolio loss. Even with a low hit rate, the convexity of deep OTM puts during real crashes (5-50x payoffs) makes the math work.

This is the Spitznagel/Universa school. The opposite (active hedge timing based on signals) is what produces the 4/30 cycle below.

## Two costly mistakes to avoid

### Mistake 1: Tactical hedge timing (the 4/30 lesson)

**What happened:** Bought 14× SPY 690P 5/22 on 4/20 at $6.76 = -$9,464. Sold on 4/23 at $7.33 = +$10,262 (small win). Re-bought 4/23 at $7.10 = -$9,940. Sold 4/30 at $3.17 = -$5,502. Net hedge P&L: **-$4,704** over 10 days.

**Why it failed:** The 4/30 close was driven by "no signals firing, reclaim time value." But the next two sessions (5/1 trading days), SPY ripped from $711 to $720.65 — straight to ATH on RSI 71. The hedge would have been needed if a reversal followed; it was closed precisely because a reversal *didn't* arrive yet.

**The lesson:** Closing a hedge because nothing is wrong is the same logic that makes you carry the hedge in the first place. If you can predict when "nothing is wrong" reliably, you don't need a hedge at all. The toggle-on/toggle-off cycle locks in drag without the convex payoff.

### Mistake 2: Correction-zone strikes for tail protection

A 5% OTM put feels like "real" insurance because it pays out earlier. But:

- It's expensive (2-3x deeper OTM premium)
- It pays out for events the portfolio could absorb anyway
- The convexity multiple in a real crash is much lower than deep OTM puts
- High premium drag eats years of "fine" markets

If the goal is tail protection, the strike should be where you genuinely *can't* survive without the payoff. For a $1M+ long-biased portfolio, that floor is roughly SPY -20% or worse.

## When to deploy

Tail hedges are a **structural program**, so the question isn't "when to open" — it's "do you commit to running the program."

Pull current state via `get_portfolio_greeks` (net delta, vega) and `get_portfolio_summary` (NLV, equity/cash split) before deciding — never estimate these from memory.

Conditions that argue **for** running the program:
- Net delta sustained >$5K per $1 SPY move (from `get_portfolio_greeks`)
- Equity exposure >50% of NLV (from `get_portfolio_summary`)
- Tech / high-beta concentration (`calculate_hedge` returns blended beta — flag if >1.3)
- Inability to quickly reduce exposure (long-term holdings, tax considerations)
- Personal risk tolerance: would a -30% drawdown force selling at the bottom?

Conditions that argue **against**:
- Portfolio is naturally hedged (long puts, short equity, market-neutral — visible in `get_portfolio_greeks`)
- Cash-heavy (>50% cash from `get_portfolio_summary` already provides downside protection)
- Active position management with tight stops
- Willing and able to liquidate fast when regime breaks

## Hedge index selection

**Default: SPY.** The choice deserves a deliberate decision, but the answer is almost always SPY for portfolios under $5M.

### Why SPY by default

| Reason | Detail |
|---|---|
| **Liquidity at deep OTM strikes** | SPY 25% OTM puts typically have 30-50x the open interest of QQQ at equivalent depth; spreads ~0.8% vs ~2.6% |
| **Spread cost compounds** | A program runs 4-6 rolls/year at deep OTM. Wider QQQ spreads add up across every entry/exit leg |
| **Beta scaling** | Tech-heavy portfolios paradoxically have *higher* trailing beta vs SPY than vs QQQ (e.g., 1.36 vs 1.13 in this book) — the SPY hedge actually scales up the protection per contract |
| **Broader coverage** | SPY captures defensive sleeves + commodity + cash positions that QQQ misses |

### When QQQ is justified

QQQ becomes the better choice when:
- Portfolio is >85% concentrated in Nasdaq-listed tech
- A specific tech catalyst is the primary risk (AGI hype peak, hyperscaler capex contraction, AI commoditization)
- Willing to accept ~17-25% higher premium per dollar of notional and wider spreads in exchange for tighter correlation

In a pure tech-bust scenario (2000-style), QQQ pays ~30% more than SPY. In a broad market crash (2008, 2020, 2022 — the modal case), SPY and QQQ pay roughly the same.

### QQQ as a tactical overlay (advanced)

For portfolios with strong tech tilt where you want to retain SPY's liquidity advantage but add tech-specific tail kicker, run a small QQQ overlay (5-10% of total hedge notional). Treat it as a separate program with its own rebalancing cycle. Only worth the management overhead at portfolio sizes >$3M, or when a specific tech catalyst is on the calendar (e.g., earnings cluster of MAG7 + hyperscaler guidance).

### Indices NOT to use

| Index | Why excluded |
|---|---|
| **XLK** (Tech Select) | Deep OTM strikes show 30-45% bid-ask spreads — mechanically unusable for tail puts even though you may own XLK shares directly |
| **SMH** (Semis) | 48% IV at 25% OTM (vs SPY 33%) and ~12% spreads. Costs ~3x more per roll for sector-specific coverage that mostly tracks QQQ |
| **IWM** (Russell 2000) | Low correlation with tech-heavy books; doesn't hedge actual exposure |
| **DIA / VTI / IVV** | Less liquid option chains than SPY with no offsetting advantage |

The default `hedge_index="SPY"` in `calculate_hedge` reflects this. Override only with deliberate justification, not because "QQQ feels more tech-y."

## Strike selection — deep OTM only

The strike defines what event you're insuring against:

| Strike depth | Event insured | Best use |
|---|---|---|
| 5-10% OTM | Corrections + crashes | Active correction hedging (NOT this playbook) |
| 15-20% OTM | Severe correction + crash | Edge of tail; covers -15%+ moves |
| **20-30% OTM** | **True crashes only** | **This playbook's sweet spot** |
| >30% OTM | Black-swan only (-30%+) | Cheapest, longest tail; needs catastrophic event |

**Default:** 20-25% OTM. Deep enough to filter out correction noise, shallow enough to keep liquidity tight on SPY/QQQ.

**Skew warning:** OTM put IV climbs as you go deeper (typical: 25% IV at 5% OTM → 35-40% IV at 25% OTM). This is the skew premium — everyone wants crash insurance. Deeper strikes still cost less in dollars despite the higher IV because the strike is so far away.

**Example pricing (SPY $720, 8/21 expiry, 14 contracts, $1.25M portfolio):**

| Strike | % OTM | Cost | % Port | IV |
|---|---|---|---|---|
| 580P | 19.5% | $5,068 | 0.41% | 28.9% |
| **540P** | **25.1%** | **$3,318** | **0.27%** | **32.9%** |
| 500P | 30.6% | $2,310 | 0.19% | 37.2% |

## Duration selection

Tail events take time to develop. A flash crash (1987-style) is the exception; most crashes (2000, 2008, 2020) unfolded over weeks-to-months with multiple legs.

| DTE | Use |
|---|---|
| <30 | Don't open — theta acceleration kills payoff before move develops |
| 30-60 | Acceptable if rolling monthly with discipline |
| **60-120** | **Preferred** — covers full crash development window |
| 120-180 | Acceptable for quarterly roll programs; vega larger |
| >180 | Vega heavy, less convexity per dollar; use only if going LEAPS |

**Default: 90-120 DTE, roll at ~30 DTE remaining.**

This captures the bulk of the time value over the life of the put while leaving enough runway in the new contract that you're never naked when an event breaks.

## Sizing

Use `calculate_hedge` with these parameters for tail-risk hedging:

| Parameter | Tail-risk default | Why |
|---|---|---|
| `hedge_index` | `SPY` | See "Hedge index selection" — almost always SPY; QQQ only with explicit justification |
| `hedge_ratio` | `0.5` | Hedge half the long delta; the other half rides the recovery |
| `delta_adjusted` | `False` | Tail-risk mode (notional sizing) — sized for full payout when puts go ITM, not 1:1 delta hedging |
| `fidelity_folder` | `~/Downloads/fidelity` (if applicable) | **Required if you hold equity in Fidelity.** Without this, sizing only covers Webull NLV |
| `crisis_multiplier` | `1.25` | Amplifies trailing beta to account for correlation spikes during crashes (tech betas inflate ~25% in real selloffs) |

The tool **rounds contracts UP** in tail-risk mode — undersizing is the costly direction.

**Why both `crisis_multiplier` and `fidelity_folder` are required:** Trailing 90-day beta understates crash beta (correlations spike to ~1.0; high-beta names amplify ~25%); the multiplier corrects for that. The Fidelity CSV is needed because Webull-only sizing misses any equity held there. Skipping either combination typically undersizes the hedge by 20-30%. Don't estimate manually — the tool needs the full picture.

**Annual budget target: 0.5-1.5% portfolio drag.** Above 2% means hedging too frequently, at the wrong IV window, or correction-hedging in disguise.

## The discipline rules (the non-negotiable part)

These are what separate a tail program from a tactical trade. Without these, the program loses money to its own toggle cycle.

| Rule | Why |
|---|---|
| **Roll at 30 DTE remaining** | Captures most of time value before theta acceleration. Don't wait until expiry. |
| **Don't close on rallies** | "Nothing is wrong" doesn't mean "no risk." That's the entire premise. |
| **Don't close on losses** | Premium decay is the *normal* outcome. Losing the entire premium most of the time is how the program is supposed to work. |
| **Only close on a rebalancing trigger** | Three valid triggers: maintenance roll (delta drift to -0.20 to -0.40), major harvest (5x+ via tranches), or routine 30-DTE roll. All three are close-and-immediate-redeploy. See Rebalancing the Program. |
| **Resize at every roll** | Re-run `calculate_hedge` (with `fidelity_folder` + `crisis_multiplier`) before each new contract — the tool reads current NLV/beta, so you never need to track portfolio drift manually. |
| **Don't short-circuit on signals** | The /hedge skill's reversal checklist is for opening discussions, not for closing this structural hedge. |

## Rebalancing the program

"Structural" refers to **the program**, not individual contracts. Contracts cycle out — via the routine 30-DTE roll, a maintenance roll when convexity has degraded, or a major-payoff harvest during a real crash. The continuity is: there is **always** a deep-OTM tail put on the books somewhere.

### Why holding a degraded contract is wrong

When SPY drops, the original deep-OTM put mutates:

| Metric | At entry (25% OTM) | After SPY -10% (now ~17% OTM) | After SPY -25% (now ATM) |
|---|---|---|---|
| Delta | -0.05 (tail) | -0.20 (moderate) | -0.50 (near-ATM) |
| Vega | tiny | medium | enormous (long massive vol) |
| Convexity | high (asymmetric payoff was the point) | half-degraded | gone (linear payoff zone) |
| Exposure type | Tail insurance | Correction insurance (mission drift) | Directional short-vol bet |

In the 25% → 17% range, the contract is no longer doing the job it was bought for — it's now correction insurance, which the playbook explicitly avoids. In the deep-ITM range, holding exposes you to vol mean-reversion (VIX 80 → 40 in days at the March 2020 nadir, with +9% SPY days during the crash). Either way, the answer is **roll, don't hold and don't exit**.

### Three rebalancing triggers (all data-driven, never gut feel)

The `/hedge` skill operationalizes these — this section is the rationale.

**Trigger 1: Maintenance roll** — put delta drifted to -0.20 to -0.40 (was -0.05; indicates ~10-15% SPY drop) AND one of: VIX retraced ≥50% from spike high, catalyst resolved, or P&L 100-300% and stalling. Restores the 25% OTM profile. Do NOT roll if delta still tighter than -0.15, VIX still climbing or above 30, SPY making new lows daily (T2 may be coming), or P&L only 50-100% (premature).

**Trigger 2: Major payoff harvest** — VIX >50, SPY down 20%+, puts deep ITM. Mechanical tranches: +400% close 50%, +900% close another 25%, +1900%+ close remaining. Don't top-tick.

**Trigger 3: Routine 30-DTE roll** — calendar-driven, no special conditions.

### Universal workflow (any trigger)

**Close + immediate redeploy in the same session.** Never close and wait. Sell the tranche → `calculate_hedge` with current SPY → buy new at 25% OTM from *current* SPY → record `decision_close` + `decision_add` action `WRITE_NEW`.

Proceeds typically buy **more contracts** at the deeper strike (lower premium + SPY drop means same dollar notional covers a deeper hedge). Result: fresher DTE + restored convexity + larger notional coverage at no net new capital. This is how the program **makes money** in a crash year and **survives** in a slow-grind year.

### The honest test

Before any non-routine roll, ask: **would I make the same decision if I couldn't see the unrealized P&L?**

- ✅ Yes → it's a principled rebalancing (delta drifted, IV crushed, catalyst resolved)
- ❌ No → you're managing regret; hold strict to the next legitimate trigger

Real Path 2 decisions are based on what the puts ARE (delta, IV state, distance from strike), not what they're worth.

## Other valid closes (no rebalancing)

| Reason | Action |
|---|---|
| **Portfolio delta materially reduced** (sold 30%+ of long book) | Downsize at next maintenance roll — don't dump mid-cycle |
| **End of program** (going to cash permanently) | Close after the next roll-equivalent date — no tactical acceleration |

## What is NEVER a valid close

"VIX dropped" / "regime cleared" / "no signals firing" (the 4/30 anti-pattern), "premium decay is killing me" (it's the program's cost), or "I'm bored holding this" (gambler's fallacy in reverse).

## Execution checklist

Before placing the order:

1. Run `calculate_hedge` with **all** of: chosen strike, expiration, `fidelity_folder` (if applicable), and `crisis_multiplier=1.25`. Use the contract count it returns — don't re-derive it.
2. Run `get_iv_metrics` for SPY — log IV Rank for entry record. Confirm Liquidity rating ≥ 3 (tight spreads); skip the strike if Liq ≤ 2.
3. Run `preview_order` to confirm cost, then place at the previewed mid or better.
4. Record the trade as a `decision_add` with action `WRITE_NEW`, source `hedge`, and `deadline` set 30 days before expiry (the platform handles the date math).

After placing:

1. Update `project_portfolio_hedge.md` memory with strike/expiry/contract count and the decision ID
2. Don't watch it. Daily price checks invite tactical second-guessing.
3. The `decision_list` deadline + roll cadence handles the reminder — no manual calendar math needed.

## Cost expectations

Realistic budget for a $1.2M portfolio at 50% notional ratio, 25% OTM, 90-120 DTE, quarterly roll:

| Item | Per cycle | Annualized |
|---|---|---|
| Premium paid (no event) | $3,000-5,000 | $12,000-20,000 |
| Premium recovered at roll (sell with 30 DTE remaining) | $500-1,500 | $2,000-6,000 |
| Net cost (no event) | ~$3,500/cycle | ~$10,000-14,000 |
| Drag % of portfolio | ~0.3% | ~1.0% |

In a real crash year (2008, 2020), one cycle's payoff (50-100x premium) covers years of drag and provides $100K+ of liquidity to deploy at the bottom. That's the whole bet.

## Realistic performance expectations

**Most tail-hedge programs fail not from bad math but from operator fatigue during benign streaks.** Re-read this section during quiet periods so future-you doesn't quit in year 4 of a 5-year benign stretch and miss the year 6 crash.

### Expected outcome distribution (rough base rates)

| Year type | Frequency | Hedge P&L | Examples |
|---|---|---|---|
| **Pure bull, no spikes** | ~50% | -0.8 to -1.0% drag | 2017, 2019, 2021, 2023, 2024 |
| **Bull with one wobble** | ~25% | -0.3 to +0.5% | 2016 |
| **Sharp correction recovered** | ~15% | +1 to +3% | 2018 Q1, Aug 2024 |
| **Sharp + slow recovery** | ~7% | +3 to +8% | 2018 Q4, 2022 H1 |
| **Real crash** | ~3% | +10 to +30% | 2008, March 2020, 2000-02 |

Over a decade: expected total return ≈ break-even to slightly positive, variance concentrated in 1-2 crash events.

### Payoff sources and failure modes

**Three payoff sources:** (1) maintenance-roll captures on sharp 10-15% moves with vol spike (3-5x via vega; most common), (2) major harvest tranches in real crashes (5x/10x/20x), (3) compounding harvest→redeploy cycles in multi-leg crashes (2008-style).

**Three failure modes:** slow grinding bear (decay outpaces drift, 2022 H1), choppy/sideways (scares resolve before triggers fire, 2015-16), and strong bull (pure drag — the program working as designed).

### Why we run it anyway

The hedge **doesn't make money** — the rest of the portfolio makes more money *because the hedge exists*. Pay ~80 bps of expected return to compress the left tail by 25+ percentage points; right tail untouched. Net benefit at beta 1.36: hedge cost ~0.83%/yr vs forgone return from de-risking instead ~2.9%/yr → **~2.0%/yr of expected return retained** by sustaining high-conviction exposure without the de-risking tax.

**Second-order payoff:** harvest proceeds during a crash become cash to deploy at the bottom. March 2020 lows were a generational entry point; a program paying $80K of harvest at SPY -25% is $80K of buying power when most operators are paralyzed.

### The hardest truth

Expect **3-7 consecutive losing years** before a crash arrives. That's the test most operators fail. **Nothing being wrong is the entire premise.**

## When this playbook DOES NOT apply

- **Active correction hedging** — use 5-10% OTM, shorter DTE, and the /hedge skill's signal-driven matrix
- **Earnings hedges** — single-stock event protection; use long puts on the specific name with 20-30 DTE
- **Sector hedges** — short-term factor exposure (XLK, SMH); evaluate per position
- **Volatility bets** — directional vol plays (long straddles, calendars); use the strategy catalog instead

For those, see [decision-framework.md](decision-framework.md) Step 3 and [strategy-catalog.md](strategy-catalog.md).

## References

- `/hedge` skill — daily evaluation framework (signal scoring, current state)
- `calculate_hedge` MCP tool — sizing
- `get_iv_metrics` MCP tool — IV environment for entry timing
- Mark Spitznagel, *Safe Haven* — academic basis for deep-OTM tail hedging
- Universa Investments public commentary — implementation patterns
