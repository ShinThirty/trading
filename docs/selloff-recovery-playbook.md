# Selloff Recovery Playbook

Playbook for capturing broad market selloff-to-recovery cycles. Fires 1-2 times per year during significant corrections (>7% drawdown). Not a recurring skill — reference this doc when `get_market_regime` shows Elevated/Crisis volatility + Downtrend.

**Core insight:** Don't trade the selloff. Trade the recovery. Long puts during a selloff means buying expensive vol at its peak. Long calls during the recovery means buying vol as it normalizes — IV crush works FOR you as the market snaps back.

This playbook has two independent legs that complement each other:

| Leg | Intent | Vehicle | Timing |
|-----|--------|---------|--------|
| **Recovery calls** | Directional leverage | SPY/QQQ long calls | After capitulation exhaustion |
| **Opportunistic CSPs** | Accumulate / Enter at discount | Highest-conviction pipeline names | During the selloff (rich IV) |

---

## When This Playbook Applies

A selloff must clear two gates before this playbook activates:

**Gate 1: Magnitude** — SPY drawdown >7% from recent high. Smaller pullbacks (3-5%) are noise, not a setup.

**Gate 2: Regime confirmation** — `get_market_regime` shows at least two of:
- Volatility: Elevated or Crisis (VIX >25)
- Trend: Downtrend (SPY below SMA50)
- Sectors: Risk-Off (defensives outperforming)

If only one dimension flips, it's a rotation, not a correction. Wait.

### Gate 3: Classify the Trigger

The trigger determines what kind of recovery to expect, which shifts the weight between legs.

| Trigger Type | Examples | Recovery Pattern | Playbook Lean |
|--------------|----------|-----------------|---------------|
| **Exogenous shock** | Pandemic, natural disaster, sudden geopolitical event | Fast V-shape — economy may be fine, fear is the driver | **Heavy on recovery calls.** Snap-back is fast and violent. |
| **Structural / liquidity** | Carry trade unwind, margin calls, forced selling, flash crash | Fast V-shape — mechanical selling exhausts itself | **Heavy on recovery calls.** Best setup for the call leg. |
| **Policy / geopolitical** | Tariffs, sanctions, trade wars, fiscal policy shifts | Variable — depends on policy reversal or adaptation | **Balanced.** Calls if reversal is likely, CSPs if grinding. |
| **Macro / rates** | Fed rate hikes, yield spikes, inflation prints | Slow grind — resolution requires economic data to shift | **Heavy on CSPs.** Recovery may take months, theta kills calls. |
| **Earnings / fundamental** | Broad earnings misses, sector-wide margin compression | Slow — market reprices growth expectations over weeks | **Heavy on CSPs.** No quick catalyst for a snap-back. |

**Key judgment:** If the trigger is **reversible** (policy change, liquidity restored, fear subsides), lean into recovery calls. If the trigger requires **economic data to change** (rates, inflation, earnings cycle), lean into CSPs and extend call DTE or skip the call leg entirely.

---

## Leg 1: Recovery Long Calls (SPY/QQQ)

This is a directional leverage trade on mean-reversion. The "catalyst" is capitulation exhaustion — measurable, not guesswork.

### Entry Signals (need 3 of 5)

| Signal | Source | Threshold |
|--------|--------|-----------|
| RSI oversold | `get_entry_signals SPY` | RSI <30 |
| VIX spike peaking | `get_market_regime` | VIX >30 but term structure normalizing (VIX3M > VIX again) |
| Breadth stabilizing | `get_market_regime` | XLY/XLU ratio bottoming or turning up |
| Volume exhaustion | `get_tradier_history SPY` | Daily volume declining from capitulation peak for 2+ days |
| Sentiment capitulation | News / `get_news_sentiment` | Wall-to-wall bearish coverage, "crash" headlines |

**The term structure flip is the strongest single signal.** During active panic, VIX > VIX3M (backwardation). When VIX3M reclaims the lead (contango returns), near-term fear is subsiding. This often leads the price bottom by 1-3 days.

### Why Calls Work Here

- **IV crush tailwind:** You buy calls while IV is still elevated from the selloff. As the market recovers, IV drops — but delta gains from the price recovery exceed vega losses from IV compression. Net effect is positive.
- **Put skew advantage:** During selloffs, put skew inflates put prices relative to calls. Calls are relatively cheaper.
- **Sharp recoveries:** Market bottoms tend to produce fast, violent bounces. Leveraged call exposure captures this better than shares.

### Strike & Expiry Selection

| Parameter | Target | Rationale |
|-----------|--------|-----------|
| Delta | 0.40-0.50 (ATM to slightly OTM) | Balanced leverage and probability |
| DTE | 45-60 days | Enough time for recovery to unfold, slow theta |
| Vehicle | SPY or QQQ | Broad market, no single-stock risk. QQQ for tech-led recoveries, SPY for broad |

### Sizing

| Rule | Limit |
|------|-------|
| Max premium at risk | 3% of portfolio (same as bearish sizing) |
| Position count | 1-2 legs max (SPY and/or QQQ, not both unless split) |

This is a market-timing trade with a statistical edge, not a fundamental thesis. Size like a bearish play — if the calls expire worthless, it shouldn't change how you trade next month.

### Management

| Rule | Trigger |
|------|---------|
| Take profit | 50% return on premium (stretch: 100%) |
| Time stop | Exit at 21 DTE if recovery hasn't materialized |
| Trend confirmation | If SPY reclaims SMA50 with rising volume, tighten stop to breakeven |
| Wrong on timing | If SPY makes new lows after entry, close at 30% loss. Re-entry allowed on new exhaustion signals. |

---

## Leg 2: Opportunistic CSPs on Conviction Names

The selloff creates discounted entries on names you already have conviction on. IV is elevated, so CSP premiums are fat. This is your framework's "Elevated vol + Downtrend + Risk-Off → Best CSP window" from [market-regime.md](market-regime.md).

### Prerequisites

- Name must already be in your pipeline with completed Steps 1-4
- Conviction must be High or Highest (Accumulate / Enter at Discount intent)
- Do NOT use the selloff to justify new names you haven't analyzed

### Strike Selection (Selloff-Adjusted)

During a broad selloff, names are already discounted. Shift strikes aggressively vs normal CSP guidance:

| Drawdown | Normal CSP Strike | Selloff CSP Strike | Why |
|----------|-------------------|-------------------|-----|
| >50% | ATM to 5% OTM | **ATM or 1 strike ITM** | You want assignment. Maximum premium. |
| 30-50% | 5-10% OTM | **ATM to 5% OTM** | Tighter strike, higher assignment probability |
| <30% | 10-15% OTM | **5-10% OTM** | One notch tighter than normal |

The elevated IV compensates for the tighter strikes — you collect more premium per dollar of risk than in a normal environment.

### Timing Within the Selloff

Unlike the recovery calls (which wait for exhaustion), CSPs can be opened **during** the selloff:

- **Early selloff (VIX 25-30):** Write CSPs at normal OTM distances. Premium is good, stock may fall further.
- **Deep selloff (VIX >30):** Tighten to ATM/ITM strikes. Premium is exceptional, you're getting paid to enter at fire-sale prices.
- **Post-earnings during selloff:** Best of both worlds — earnings IV + selloff IV = maximum premium. If a conviction name reports during the correction, sell the CSP through earnings.

### Sizing

Standard framework rules apply, with one addition:

- 60% CSP collateral cap still holds — don't deploy everything into CSPs during the panic
- Reserve at least 30% of cash for T2 scale-in if the selloff deepens
- If running both legs simultaneously, recovery calls + CSP collateral combined should not exceed 70% of available capital

---

## How the Two Legs Interact

The legs serve different intents and hedge each other's timing risk:

| Scenario | Recovery Calls | CSPs | Net Effect |
|----------|---------------|------|------------|
| **V-shaped recovery** | Big winner (delta + IV crush tailwind) | Expire worthless, keep premium | Both legs profitable |
| **Slow grind recovery** | Moderate winner, theta hurts | Likely expire worthless, keep premium | Both profitable but smaller |
| **Deeper selloff after entry** | Loser (close at stop) | Assigned at discount + fat premium cushion | Calls lose, but you own names you wanted cheaper |
| **Sideways chop** | Theta erodes calls | Premium decays in your favor | Calls lose, CSPs win |

The CSPs act as a natural hedge against being early on the recovery calls. If you're wrong about the bottom, you at least entered your highest-conviction names at a discount with elevated premium.

---

## Sector Variant: Bellwether Earnings Cascade

The same selloff-recovery mechanics apply at the sector level when a bellwether stock misses earnings and drags the entire sector in sympathy. This is a smaller-scale, more frequent version of the broad market playbook — happens 2-3 times per earnings season.

**Key difference from the broad playbook:** The vehicle is your individual pipeline names, not sector ETFs. The ETF already reflects the bellwether's miss. You're trading the divergence between your quality name and the damaged bellwether — once the market differentiates (usually 1-2 weeks), quality names diverge from the actual miss.

### When This Applies

- A sector bellwether misses earnings (e.g., ServiceNow drags SaaS, Intel drags semis)
- Your pipeline names in that sector sell off in sympathy
- Your names' fundamentals haven't changed — the selling is guilt-by-association

### Entry Sequence

1. **Bellwether misses, sector dumps.** Don't act on day one — sympathy selling can persist for 2-3 days.
2. **Re-run `get_entry_signals`** on your pipeline names in the affected sector. Confirm conviction is intact and no new Negative factors emerged.
3. **Check `get_company_news`** — verify your name has no independent bad news hiding behind the sector noise.
4. **Enter on your names:**
   - **CSPs** if IV is elevated from the cascade (usually is — sector-wide IV spikes on bellwether misses)
   - **Long calls** once IV starts normalizing (3-5 days post-event) if the name is deeply discounted and you have highest conviction
   - **Direct buy** if IV is low and the discount is meaningful

### Why Not Sector ETFs

- The ETF contains the bellwether that actually missed — it's dragging the basket down
- You're betting on divergence (your name recovers, bellwether doesn't), not sector recovery
- Individual name selection IS the edge — the ETF dilutes it

### Sizing

- Same as standard framework per-name sizing (conviction tier determines allocation)
- Max 2 names per sector cascade event — don't overload on one sector's sympathy selling
- If the cascade coincides with a broader market selloff, total deployment across both playbooks shares the same capital pool

### Management

- Take profit when your name recovers to pre-cascade levels (the sympathy discount closes)
- If your name reports earnings within 2-3 weeks of entry, hold through — its own results are the ultimate thesis test
- If the name doesn't diverge within 2 weeks, reassess — maybe the damage is fundamental, not sympathy

---

## L3 Expansion: Selloff Leg with Spreads

At L2, the selloff side is limited to CSPs (selling premium). Long puts during the selloff are poor risk/reward due to peak IV pricing. With L3 approval (target 2027):

**Bear put spreads during the selloff** unlock the selloff as a directional trade:
- Selling the expensive vol on one leg offsets buying it on the other — IV cost largely nets out
- Capital per contract drops significantly (spread width vs full put cost), allowing 2-3x the contracts for the same premium budget
- Defined risk on both sides means the double-headwind blowup scenario (wrong on direction + IV crush) is capped
- Can run selloff spreads on SPY/QQQ alongside the recovery calls — capturing both legs of the V-shape

This would add a third leg to the playbook: bearish spreads opened during the selloff, closed at exhaustion (where the recovery calls take over).

---

## Post-Playbook Transition

Once the recovery is underway (SPY above SMA50, VIX <20, breadth broadening):

1. **Close recovery calls** at profit target or when momentum slows
2. **Manage CSPs** per normal framework — let expire or roll per [strategy-catalog.md](strategy-catalog.md)
3. **Return to standard pipeline workflow** — the selloff window is closed, normal framework applies

---

## Tools Checklist

```
Setup (daily during selloff):
1. get_market_regime                    — regime dimensions + VIX term structure
2. get_entry_signals SPY               — RSI, SMA, momentum for recovery timing
3. get_iv_metrics SPY,QQQ              — IV Rank for option pricing

Recovery call entry:
4. get_option_expirations SPY          — find 45-60 DTE expiry
5. get_option_chain SPY <expiry>       — strike selection at target delta

CSP entry (per conviction name):
6. get_entry_signals <TICKER>          — confirm conviction still intact after selloff
7. get_option_expirations <TICKER>     — find 30-45 DTE expiry
8. get_option_chain <TICKER> <expiry>  — ATM/ITM put selection
```
