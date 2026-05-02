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
| `hedge_index` | `SPY` | Most liquid; `QQQ` if portfolio is overwhelmingly tech (>80%) |
| `hedge_ratio` | `0.5` | Hedge half the long delta; the other half rides the recovery |
| `delta_adjusted` | `False` | Tail-risk mode (notional sizing) — sized for full payout when puts go ITM, not 1:1 delta hedging |
| `fidelity_folder` | `~/Downloads/fidelity` (if applicable) | **Required if you hold equity in Fidelity.** Without this, sizing only covers Webull NLV |
| `crisis_multiplier` | `1.25` | Amplifies trailing beta to account for correlation spikes during crashes (tech betas inflate ~25% in real selloffs) |

The tool **rounds contracts UP** in tail-risk mode (`delta_adjusted=False`) — undersizing is the costly direction.

**Why crisis_multiplier matters:** Trailing 90-day beta is what the market looks like during normal conditions. During crashes, correlations spike toward 1.0 and high-beta names amplify. A trailing beta of 1.61 typically behaves like ~2.0 in a real selloff. Without the multiplier, a "50% notional hedge" actually covers ~37% of true exposure when it matters most.

**Why fidelity_folder matters:** The tool reads Webull positions via API. If you also hold Fidelity equity, those positions and their NLV are invisible without the CSV folder. Sizing against partial NLV undersizes the hedge.

**Reference call** (current portfolio shape, May 2026):

```
calculate_hedge(
  hedge_index="SPY",
  hedge_ratio=0.5,
  strike=540,
  expiration="2026-08-21",
  fidelity_folder="~/Downloads/fidelity",
  crisis_multiplier=1.25
)
```

Returns 19 contracts at $4,503 (0.29% of $1.56M portfolio). Trailing beta 1.36 → crisis-adjusted 1.70. Without `fidelity_folder` and `crisis_multiplier`, the same call returns 14 contracts — a 26% undersize.

Note: including Fidelity actually *lowers* the trailing beta (1.61 → 1.36) because the Fidelity equity (ISRG, PGR, V, RDDT, RMBS) is more defensive than the Webull tech book. But it raises total NLV ($1.25M → $1.56M), so contract count still goes UP. The point: don't try to estimate either factor manually — the tool needs the full picture to size correctly.

**Annual budget target: 0.5-1.5% portfolio drag.** Above 2% means you're either hedging too frequently, hedging at the wrong IV window, or correction-hedging in disguise.

## The discipline rules (the non-negotiable part)

These are what separate a tail program from a tactical trade. Without these, the program loses money to its own toggle cycle.

| Rule | Why |
|---|---|
| **Roll at 30 DTE remaining** | Captures most of time value before theta acceleration. Don't wait until expiry. |
| **Don't close on rallies** | "Nothing is wrong" doesn't mean "no risk." That's the entire premise. |
| **Don't close on losses** | Premium decay is the *normal* outcome. Losing the entire premium most of the time is how the program is supposed to work. |
| **Only close on payoff** | If puts hit 5x+ during a crash, take 50% of contracts off, let rest ride further. |
| **Resize at every roll** | Re-run `calculate_hedge` (with `fidelity_folder` + `crisis_multiplier`) before each new contract — the tool reads current NLV/beta, so you never need to track portfolio drift manually. |
| **Don't short-circuit on signals** | The /hedge skill's reversal checklist is for opening discussions, not for closing this structural hedge. |

## When to close (only payoff scenarios)

The only valid reasons to close before the 30 DTE roll:

1. **Multi-bagger payoff during a crash.** Use `get_portfolio_summary` to read current option P&L %; when the row shows ≥400% (5x), close 50% of contracts to lock in a portion. Let the rest ride; if the crash deepens, the remaining contracts compound.
2. **Portfolio delta materially reduced.** If you sold 30%+ of the long book and no longer need 50% notional coverage, downsize at next roll (don't dump mid-cycle).
3. **End of program.** If you're permanently exiting the strategy (going to cash, etc.), close after the next roll-equivalent date — don't accelerate the exit on a tactical signal.

That's it. No "VIX dropped" close. No "regime cleared" close. No "premium decay is killing me" close.

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
