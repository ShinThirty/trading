# Fiscal Dominance Playbook

This doc covers **one specific macro path**: a loss of monetary-policy credibility — most concretely, a politically-pressured Fed cutting rates *into* re-accelerating inflation. It is an **overhang overlay**, not a regime score.

[bear-regime-playbook.md](bear-regime-playbook.md) fires on a 9-dimension composite regardless of *what kind* of bear is forming. This doc handles the case that composite structurally under-weights — because the defining signal here (a Fed rate cut) reads as *accommodation* to almost every other framework. The composite's Curve dimension gives a Bear Steepener only 0.5 of a possible point; on its own that never moves a tier. So this overhang must be tracked as a named macro overhang per [decision-framework.md](decision-framework.md)'s "Active Macro Overhangs" step — it will escalate while the score still reads Watchful.

## Why this needs its own playbook — three inversions

Every other bear playbook assumes a recession-shaped bear. This path inverts three reflexes:

1. **The de-risk signal is inverted.** Everywhere else a Fed cut is accommodation and a reason to add risk. Here the cut *is* the damage — it is the policy error that un-anchors inflation expectations. The cut is the de-risk bell, not the green light.
2. **The safe haven is broken.** A recession bear has the long end *rallying* (flight to quality) — Treasuries hedge the equity book. In a fiscal-dominance bear the long end *sells off*. Long-duration Treasuries and bond proxies are the loss, not the hedge. The flight-to-quality reflex fails.
3. **The trigger is a head-fake.** Negative real rates drive a nominal melt-up *first*; the de-rating comes *second*, when the bond market revolts. A drawdown-triggered playbook fires too late — you must act on the rate signal, before the equity drawdown.

## The scenario

**Fiscal dominance** = monetary policy subordinated to financing the deficit and/or to political will, rather than to the inflation mandate. The concrete 2026-27 trigger path:

Fed chair transition (Powell's chair term ends 2026) → a dovish political appointee → a rate cut delivered *into* a re-accelerating core inflation print → the bond market reads a loss of Fed independence → long-run inflation expectations un-anchor → term premium widens → **bear steepener**: the front end falls on the cuts, the long end *rises* on lost credibility.

This is the third row of the three-cut table — the one cut type that is a de-risk signal:

| Cut type | Context | Signal |
|---|---|---|
| **Insurance / mid-cycle** | Cutting into clean disinflation, growth soft but fine — 1995, 2019 | Risk-ON. Not this playbook. |
| **Recession cut** | Cutting because labor/credit is cracking — 2001, 2007 | De-risk — but long end *rallies*; use [bear-regime-playbook.md](bear-regime-playbook.md). |
| **Policy-error / fiscal-dominance cut** | Cutting into *re-accelerating* inflation under political pressure — Burns 1970s | De-risk hard — long end *sells off*. **This playbook.** |

The FOMC statement reads identically in all three. What separates them is the *inflation backdrop at the time of the cut* and *the long end's reaction to it*.

Why it matters now: the AI build-out is increasingly **debt-funded** — hyperscaler bond issuance, SPV financing, neocloud credit, SpaceX/xAI's GPU-as-debt sale-leasebacks. That term debt is priced off the long end, not fed funds. A bear steepener raises the cost of the build-out's *forward* financing even as the Fed cuts the overnight rate. The most leveraged, most duration-sensitive, most concentrated part of the market is therefore the prime fracture candidate.

## Trigger ladder

Staged on **observables**, not price. Each stage inherits the prior stage's actions.

| Stage | Observable condition | Posture |
|---|---|---|
| **Latent** | Overhang identified; chair succession not yet a market focus; inflation behaving. | Awareness only. No action. |
| **Watch** | Dovish chair nominee dominates the narrative, OR core CPI/PCE re-accelerating 2+ consecutive prints while Fed rhetoric stays dovish. Breakevens drifting up. | Inventory positions into the five buckets. Confirm tail hedge sized. |
| **Confirming** | An FOMC cut (or near-certain signal) lands coincident with a re-accelerating core print. **Read the long end's 48h reaction.** | 30Y up + breakevens widening → escalate to Active. 30Y flat/down + breakevens stable → de-escalate to Watch. |
| **Active** | `get_yield_curve_state` prints **Bear Steepener** on the 4w window; 30Y up sharply over ~4-6 weeks with 2Y flat/down; breakevens at cycle highs. | Execute the composition change (see buckets). |
| **Disorderly** | Long end moving disorderly; credit event in AI-capex financing (SPV/neocloud distress, IG spreads gapping); or an official YCC / large-scale-asset-purchase response to cap yields. | Crisis actions — max hedge, sell rallies, freeze entries. |

The actionable event is the **Watch → Confirming → Active transition**, not the absolute level of any one yield. A single hot CPI print is not the overhang; a cut delivered *into* one, with the long end revolting, is.

### Stage detail

**Watch.** Sort every position into the five buckets below — the "inventory" pass, done once at Watch and refreshed each `/review`. Run `/hedge` if not done this month. Do *not* trim on Watch alone; the overhang may dissolve (a hawkish chair, inflation rolls over).

**Confirming.** The decision checkpoint. The cut has happened or is near-certain. Pull `get_yield_curve_state` and the breakeven series (FRED `T10YIE`, `T5YIFR`, `DGS30` via `get_economic_data`) in the 48h after the FOMC. The long end's reaction *is* the decision: a rising 30Y with widening breakevens confirms the policy-error read and escalates to Active. A falling/flat long end means the market still believes the Fed — de-escalate, the overhang is not firing.

**Active.** Execute the composition change. De-risk here means **changing the mix, not going to cash** (see The Inverted-Signal Rule). Trim debt-funded-capex beta on strength, write CCs on extended winners, lean the debasement sleeve, tighten CSP discipline.

**Disorderly.** Inherits [bear-regime-playbook.md](bear-regime-playbook.md) Crisis actions and [tail-hedge-playbook.md](tail-hedge-playbook.md) Trigger 2 (harvest tranche). The distinction from a normal Crisis: do **not** rotate proceeds into long-duration Treasuries — the long end is the epicenter.

## Position classification — five buckets

At Watch, sort every holding across all accounts into a primary bucket. Each bucket has a stage-gated action.

| Bucket | What belongs here | Active-stage action |
|---|---|---|
| **1. Debt-funded-capex beta** | Hyperscalers + AI-infrastructure suppliers whose forward growth depends on the build-out continuing *and* on access to cheap term debt — GPUs, the SPV/neocloud-financed names. | Trim 25-50% on strength (not at lows). The fracture cohort. |
| **2. Long-duration multiple** | High-multiple growth where value is mostly far-future cash flows — de-rates mechanically as the long end rises, regardless of fundamentals. (P/S >12 or PEG >3, per bear-regime-playbook's cohort cut.) | Pause accumulation. Write CCs on winners >30% from cost. No new long calls. |
| **3. Debasement winners** | Gold, BTC, real assets, energy/commodities. Beneficiaries of negative real rates + currency debasement. | The rotation destination. The BTC sleeve is the existing vehicle. |
| **4. Short-duration cash generators** | Near-dated cash flows, pricing power, low rate-sensitivity — genuine diversifiers. | Hold. Relative outperformers in this regime. |
| **5. Vol-selling exposure** | Not a holding type — a risk *exposure*: CSPs, the wheel, CCs. Short premium into a rising-IV regime. | See account map — widen strikes, shorten duration, accept lower utilization. Do not sell vol cheap. |

A name can be both bucket 1 and bucket 2 (an unprofitable, debt-funded, high-multiple supplier is the worst-positioned holding in this regime — both forces hit it). Buckets 1+2 overlap heavily with the existing AI-capex book; that concentration is the point of the exercise.

The live mapping of *current* positions to these buckets is **run, not stored** — generate it at the Watch-stage inventory and refresh each `/review`. A hardcoded snapshot in this doc would rot within weeks.

### Offensive expression — shorting buckets 1 and 2

The bucket actions above are *defensive* — trim, cover, pause. But if the bucket-1 fracture thesis is high-conviction, the repricing is also a **trade**, not only a risk to dodge. Three rules govern when that is allowed:

**Enter before the repricing is visible, not after.** The bearish trade is opened during the head-fake melt-up (Watch / Confirming), when bucket 1/2 names are at their highs *and* IV is still cheap. By the Active stage IV has popped and the move is half-done — initiating long puts there pays peak vol for the back half of the trade, which the catalyst-IV-trajectory rule explicitly warns against. **Active stage is harvest-or-hold, never initiate.**

**Long puts only — size for that constraint.** L3 is denied, so there are no bear spreads; the only bearish instrument is the long put. That makes this a structural purchase of expensive convexity: buy when IV is low, size small, define the loss up front, time-box it, and accept that most expire worthless. This is tail-hedge discipline, not bearish-framework discipline.

**Buckets 1 and 2 short differently — and bucket 2 mostly should not be shorted at all:**

| Bucket | Bearish expression | Why |
|---|---|---|
| **1. Debt-funded-capex beta** | Single-name long puts on the most over-levered, most stretched name. | Idiosyncratic — cracks on a credit event. Genuine edge, and *not* covered by the index tail hedge. |
| **2. Long-duration multiple** | None as a standalone trade — upsize the tail hedge instead. | Derates mechanically and broadly with the long end = the *same exposure* as the index tail hedge. A separate bucket-2 short double-counts it. |

**Bookkeeping.** A long put on a name you *own* is a protective put (a hedge), not a bearish trade. The outright short only exists in puts held *beyond* your share count, or on names you don't hold. De-risk and the short are therefore one continuum — trim bucket 1 on melt-up strength, and the puts beyond your remaining share count *are* the directional position. Track them as separate `decision_add` entries (hedge vs. directional) so the books don't blur.

**Discipline caveat.** This is a *macro-derating* short, not a *deterioration* short. The [bearish-framework.md](bearish-framework.md) assumes a failing business whose bad fundamentals catch you if you are early. A macro short has no such floor — buckets 1/2 are mostly good businesses at stretched prices. Keep it in the small, defined-cost, time-boxed lane; "thesis right ≠ trade right" bites hardest here.

## Account-by-account application

The buckets land differently across the account structure. Account *types*, not a position list:

- **Wheel accounts (Fidelity HSA, Webull Roth).** Home of bucket 5. In a rising-IV regime the CSP premium looks fattest right before it isn't — that fat premium is the market pricing the move you're about to be run over by. Discipline: widen strikes (deeper OTM), shorten duration (faster reassessment), accept lower utilization. Do not chase yield. Wheel mechanics are unchanged; the *aggressiveness* dials down.
- **Position-building accounts (the three Fidelity accounts).** Home of buckets 1, 2, 4. This is where the composition change executes: trim bucket 1 on strength, pause bucket 2 accumulation and overlay CCs, let bucket 4 ride. Freeze new accumulate entries at Active.
- **Tail hedge.** Covers the whole book — see [tail-hedge-playbook.md](tail-hedge-playbook.md). This regime is squarely a tail-hedge scenario, but note the head-fake: the melt-up may come first and the puts will feel wrong before they feel right. That is the playbook working, not failing — do not close on the melt-up.
- **BTC sleeve.** Bucket 3. The cleanest expression of the debasement trade and its own sleeve already — this regime is structurally supportive of it; size per the existing sleeve framework, not as a panic rotation.

## The inverted-signal rule

The two rules that separate this playbook from the reflexes it overrides:

1. **De-risk on the cut + long-end reaction, not on a drawdown.** The drawdown is the *consequence*; by the time it arrives the repricing is underway. The signal is the Confirming-stage long-end reaction. Act there.
2. **De-risk = change composition, not go to cash.** Negative real rates make cash a guaranteed real loss, and the nominal melt-up can run hard. De-risking means rotating the *mix* — out of buckets 1/2, into buckets 3/4, hedge intact — not de-grossing to cash. Going to cash trades one un-hedged exposure (equity drawdown) for another (inflation erosion).

The honest test before acting at Confirming: **would I treat this cut as a de-risk signal if the long end had *rallied* on it?** If no — then it is the long-end reaction, not the cut headline, doing the work. Good. If you would de-risk regardless of the long end, you are reacting to the FOMC headline, which reads identically across all three cut types.

## What does NOT work here

| Reflex | Why it fails |
|---|---|
| **Flight to long-duration Treasuries** | The long end is the epicenter of the selloff. Duration is the loss, not the hedge. |
| **Going to cash** | Negative real rates — cash is a guaranteed real loss while the nominal melt-up runs. |
| **Selling vol for income** | IV is rising; CSP/CC premium looks richest right before the move. Harvesting it is selling insurance into a fire. |
| **"Buy the Fed-cut dip"** | The cut is the de-risk signal, not the all-clear. Buying the dip buys the policy error. |
| **Waiting for `get_bear_regime_score` to escalate** | The composite under-weights this path (Bear Steepener = 0.5/9). It will lag. This overhang escalates on its own ladder. |

## Monitoring cadence

- **`/briefing` (daily)** — long-end + breakeven check: `get_yield_curve_state` regime label, `DGS30` and `T10YIE` direction. A move toward Bear Steepener surfaces the overhang.
- **`/review` (biweekly)** — reassess the trigger-ladder stage; refresh the five-bucket position inventory if stage ≥ Watch.
- **`project_fiscal_dominance_watch.md` memory** — records the current live stage and the last long-end read, so `decision-framework.md`'s Active Macro Overhangs step picks it up. Update the stage there whenever the ladder moves.

## Calibration status

- The trigger-ladder thresholds (breakeven drift, 30Y move sizes) are **educated guesses**, deliberately left qualitative pending a live episode. Tighten them once there is one real observation.
- The three-cut distinction is the load-bearing concept; the bps thresholds are not. Do not let a missed numeric threshold override a clear policy-error read.
- Revisit the bucket cohort cut (P/S >12 or PEG >3) in step with [bear-regime-playbook.md](bear-regime-playbook.md)'s — they should stay aligned.

## Companion reads

- [decision-framework.md](decision-framework.md) — Active Macro Overhangs step; this doc is the mechanics for one named overhang
- [bear-regime-playbook.md](bear-regime-playbook.md) — generic composite-score bear playbook; this doc is the override for the case it under-weights
- [tail-hedge-playbook.md](tail-hedge-playbook.md) — structural OTM-put program; the hedge leg of this regime
- [valuation-regime.md](valuation-regime.md) — Bear Steepener regime definition + ERP compression mechanics
- [market-regime.md](market-regime.md) — dimensional reads feeding the macro picture
