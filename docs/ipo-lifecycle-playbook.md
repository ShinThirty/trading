# Hot-IPO Lifecycle Playbook

How the standard first-year IPO catalysts actually move a hot, popped, pre-profit
stock — and the catalyst-specific entry rules that fall out of the data.

This is the **timing** companion to [pre-profit-growth-framework.md](pre-profit-growth-framework.md):
that framework decides *whether* a pre-profit IPO is worth trading; this playbook decides
*when in the IPO's lifecycle to act*. Use it when a pipeline name is < 12 months public and
the thesis hangs on an IPO-mechanics catalyst — a lockup-expiry fade, a post-IPO momentum
unwind, or a first-print event trade.

The core finding up front, because it overturns the intuitive trade: **the 180-day lockup
expiry is the wrong event to target.** In every comp studied it was a non-event or a
relief bottom — never the catastrophe. The catastrophe is earlier (post-IPO premium decay)
or sharper (the first earnings prints). Trade those instead.

---

## The study

### Sample (n = 7)

Tiered: tight structural analogs for CBRS studied in depth, plus a broader hot-IPO cohort
for catalyst base rates. Day-1 pop is measured close-to-IPO-price.

| Ticker | IPO | Price | Day-1 close | Pop | Why included |
|--------|-----|-------|-------------|-----|--------------|
| **CRWV** | 2025-03-28 | $40 | $40 | **0%** (priced below $47–55 range — a "broken" IPO) | Neocloud, single-customer-concentrated, capex-heavy. Closest structural analog to CBRS. |
| **ARM** | 2023-09-14 | $51 | ~$61 | +19% | AI-chip IP licensor; SoftBank held ~90% post-IPO. Strategic-holder lockup case. |
| **ALAB** | 2024-03-20 | $36 | $70 | +94% | AI interconnect silicon; hot pop, VC-heavy float. |
| **SNOW** | 2020-09-16 | $120 | $240 | +100% | Pre-profit hyper-growth; record-setting pop. |
| **RDDT** | 2024-03-21 | $34 | $46 | +35% | Hot platform IPO, moderate pop. |
| **ABNB** | 2020-12-10 | $68 | $139 | +104% | Marquee 2020 IPO. |
| **DASH** | 2020-12-09 | $102 | $175 | +72% | Marquee 2020 IPO, capex-light but pre-profit. |

**Method.** Weekly OHLCV across each name's first ~13–15 months; daily OHLCV drilled into
the lockup windows. Catalyst dates from public earnings calendars and the standard 180-day
lockup convention. Percentages are descriptive figures off the pulled price series, rounded.

**Limitations — read these before trusting any number.**
- n = 7 is a pattern study, not a statistical proof. Treat the patterns as priors, not laws.
- SNOW / ABNB / DASH drawdowns (Dec 2020 → mid-2021) overlap the broad SaaS/growth rate-driven
  selloff — their declines are partly market beta, not pure IPO mechanics.
- Lockup dates are the 180-day convention; several names (SNOW, CRWV) had staggered or
  early-release tranches that blur the exact date. The *pattern* survives the imprecision.
- Historical IV term structure is not retrievable through our tooling, so the IV findings
  are derived from price/realized-vol behavior plus the known post-IPO IV-crush mechanic.

---

## The first-year arc — four phases

Every hot IPO in the sample traced the same four-phase shape. Knowing which phase a name
is in *is* the entry signal.

```
 Phase 1        Phase 2              Phase 3            Phase 4
 POP & FLIP     PREMIUM DECAY        DEAD ZONE          FUNDAMENTAL RE-RATE
 day 0–~wk 6    month ~1–5           month ~5–7         first "real" earnings beat
 ───────────────────────────────────────────────────────────────────────────────►
   ╱╲                                                            ╱╱╱
  ╱  ╲╲                                                       ╱╱╱
 ╱     ╲╲╲                                              ╱╱╱╱
          ╲╲╲╲╲                                  ╱╱╱╱╱
                ╲╲╲╲╲___________________________╱
                        (lockup expiry lives in here — a non-event)
```

**Phase 1 — Pop & flip (day 0 → ~week 6).** Day-1 pop is set by allocation scarcity and
flipper demand, not by any view on fair value. It peaks within days to two weeks, then the
flipper base exhausts. The pop is *not* a price you should anchor to.

**Phase 2 — Premium decay (month ~1 → ~5).** The defining move of year one. The day-1
premium bleeds out as momentum buyers leave and no natural long-term holder base has formed
yet. **This is the first and usually the deepest drawdown — and it has nothing to do with
lockup.** Magnitudes from peak to the Phase-2 trough:

| Name | Early peak | Phase-2 trough | Decline | Notes |
|------|-----------|----------------|---------|-------|
| ALAB | $95 (wk 3) | $36 (~mo 4.5) | **−62%** | The entire +94% day-1 pop fully retraced to ~IPO price |
| DASH | $256 (mo 1.5) | $110 (~mo 5) | **−57%** | |
| CRWV | $187 (mo 2.5) | $84 (~mo 4.5) | **−55%** | (plus a second earnings-driven leg, below) |
| SNOW | $429 (mo 2.5) | $205 (~mo 6) | **−52%** | overlaps the 2021 growth selloff |
| ABNB | $220 (mo 2) | $130 (~mo 5) | **−41%** | overlaps the 2021 growth selloff |
| ARM  | $69 (wk 1) | $47 (~mo 1) | **−32%**, then 4.5 months dead below IPO price |

A **40–60% drawdown from the early peak within the first ~5 months is the base case**, not
the tail.

**Phase 3 — Dead zone (month ~5 → ~7).** After the decay exhausts, the stock goes
range-bound and quiet. IV crushes. **The 180-day lockup expiry lives here** — and is a
non-event (see below). This is the accumulation window for a fundamental thesis and the
worst window to hold decaying long options.

**Phase 4 — Fundamental re-rate.** The first earnings print that the *real* (non-flipper)
holder base can underwrite re-rates the stock, usually violently. CRWV, ARM, SNOW and RDDT
each 2–4×'d off a Phase-3/4 base on a single beat. This is a fundamental event, not a
mechanical one — it does not happen on a schedule.

---

## Catalyst-by-catalyst findings

### 1. Day-1 pop / quiet-period end (~day 25)

The pop is flipper liquidity. Quiet-period end (~25 days post-IPO, when underwriters may
publish initiations) produced only a minor, noisy bump in the data — not a tradeable edge
on its own. **Neither is an entry; both are part of Phase 1 noise.**

### 2. First earnings as a public company — the real binary

This is the highest-information event of year one. It is a gap, not a drift:

| Name | First print | Reaction |
|------|-------------|----------|
| CRWV | Q1 2025 (May) | **Ignition** — kicked off the run from $54 toward $187 |
| SNOW | Q3 FY21 (Dec) | **Ignition** — ran to $429 |
| RDDT | Q1 2024 (May) | **Positive** — $47 → $53 week, ran toward $66 |
| ARM  | Q3 FY24 (Feb, ~mo 5) | **Ignition** — +131% over two weeks (AI-mania quarter) |
| ALAB | Q1 2024 (May) | Mild negative — $77 → $70 |
| CRWV | Q2 2025 (Aug) — *2nd print* | **Crash** — −36% in 3 days, −43% peak-to-trough |
| CRWV | Q3 2025 (Nov) — *3rd print* | **Crash** — −45% peak-to-trough |

The first one or two prints carry the binary repricing. For a framework-reject name, the
first print is where the bear thesis is *confirmed or killed* — and it lands months before
the lockup.

### 3. The 180-day lockup expiry — consistently a non-event

This is the headline finding. The actual lockup date in all seven comps:

| Name | Lockup (≈180d) | Price behavior around the date |
|------|----------------|--------------------------------|
| **ALAB** | ~2024-09-16 | **The exact bottom.** Lockup-day close $43.86 → +16% over the next 5 sessions. |
| **CRWV** | ~2025-09-24 | **Non-event.** Mid-recovery; rose from $112 (T−8) into $133 (date). |
| **ARM**  | ~2024-03-12 | **Non-event.** Chopped $122–148; SoftBank (90% holder) had publicly signaled no intent to sell. |
| **RDDT** | ~2024-09-17 | **Non-event.** Stock rose through it, $58 → $67. |
| **DASH** | ~2021-06-07 | **Non-event.** Rising into and through the date. |
| **SNOW** | ~2021-03-15 | Window ≈ the cycle low — but that low was the broad SaaS/rate selloff, not the lockup. |
| **ABNB** | ~2021-06-08 | Window ≈ the cycle low — same broad-selloff caveat. |

**Why the lockup is a dud as a catalyst trade:** it is the single most telegraphed event in
markets. Everyone knows the date and the unlocking share count months ahead. That certainty
gets discounted *in advance* — as a slow drift in the weeks *before* the date, not as a gap
*on* it. By the date itself the supply fear is exhausted, holders rarely dump into one
print, and the *removal of the overhang* ("uncertainty resolved") frequently marks a relief
bottom. **Buying puts that expire just after the lockup date is fighting the base rate.**

### 4. WHO holds the locked shares — the one variable that matters

The lockup's bite is set by holder composition, not share count:

- **Strategic holders** (corporates, sovereign-linked institutions, founders staying on)
  rarely sell into the unlock. ARM's lockup was a non-event precisely because SoftBank held
  ~90% and *said* it would not sell. A strategic-heavy float defuses the lockup.
- **Financial sponsors** (VCs, growth funds) have LPs to return capital to and *will*
  distribute or sell. A VC-heavy float is what produces the anticipatory pre-date bleed.
- **Forced sellers** are the genuine tail: a holder under regulatory, redemption, or
  geopolitical pressure can convert from "strategic" to "motivated seller." This is the only
  way a lockup becomes a real down-catalyst — and it shows up as *news*, not as the date.

### 5. Index inclusion

In the 2020–2025 study sample, S&P / Nasdaq-100 inclusion arrived slowly — after the
standard ~12-month seasoning — landing in Phase 3/4 as a modest positive technical. It was
not cleanly isolable; for those comps, treat it as a small tailwind, not an entry signal.

**This finding is now time-limited.** The spring-2026 fast-track rules (see the addendum)
pulled inclusion forward by up to a year — it can now land *inside Phase 2* as a scheduled,
dated, forced-buyer event large enough to interrupt the premium decay. For any IPO listing
after May 2026, index inclusion is no longer a footnote — model it as a catalyst with a date.

---

## Seven patterns

1. **Premium decay is the first and biggest drawdown, and it is not the lockup.** A 40–60%
   fall from the early peak inside the first ~5 months is the base case for a hot, popped IPO.
2. **Lockup expiry is a non-event or a relief bottom.** The overhang is priced in *before*
   the date via an anticipatory bleed; the date itself resolves uncertainty.
3. **Earnings, not lockup, is the catalyst that gaps the stock.** The first 1–2 public prints
   carry the binary — both the ignitions and the crashes in the sample were earnings-driven.
4. **Holder composition determines lockup impact.** Strategic-heavy float → lockup defused.
   VC-heavy float → anticipatory bleed. Forced seller → the only real down-catalyst, and it
   arrives as news.
5. **The dead zone is real.** Expect a long flat/quiet stretch (often months 4–7) between the
   decay trough and the fundamental re-rate. Worst window for decaying long options; best
   window to accumulate a fundamental thesis.
6. **The day-1 pop is a flipper's price, not a holder's price.** Never anchor entry — long or
   short — to the pop or to the IPO price. Anchor to the phase.
7. **The decay is a low-volume bleed — do not wait for a volume spike to confirm it.** Daily
   volume measured across the six comps with a Phase-2 decay leg: the rollover off the early
   peak runs on flat-to-falling volume every time (CRWV 31M→8M, ARM 75M→8M, ALAB 11M→1–2M;
   SNOW / DASH / ABNB the same). Volume expands only at four things — the day-1 pop, earnings
   gaps, macro capitulation, and lockup/index events — never at the rollover itself. Phase 2
   is flipper exhaustion, not a breakdown from a base; buyers leaving *is* fading volume.
   Confirm the rollover with price structure (sustained lower closes / lower highs), not with
   volume expansion — a volume spike during the drift signals a different event.

---

## Entry-signal rules

### For a bearish / fade thesis (the CBRS case)

| Window | Setup | Entry signal | Structure |
|--------|-------|--------------|-----------|
| **Best — Phase 2 decay fade** | Post-IPO momentum visibly rolls over | Stock breaks its day-1 close *and* its post-IPO uptrend on a sustained sequence of lower closes / lower highs — volume flat-to-fading is normal and confirming (a volume *spike* instead signals a news/earnings event, a different trade); IV Index has come off the post-IPO peak (puts cheaper) | Long put or bear put spread, 30–60 DTE; this is months ~1–4, well before any lockup |
| **Sharpest — first-print event trade** | Framework-reject thesis intact going into the first public earnings | Defined-risk bearish structure placed *before* the print, only if IV has not already priced the full gap | Bear call spread (sell rich IV) or long put expiring just after the print |
| **Conditional — pre-lockup anticipatory bleed** | VC-heavy float, no strategic-holder no-sell signal | Enter T−6wk to T−3wk before the lockup date; **exit by T−1wk / the date** | Short-dated put or bear spread — a drift trade, not a gap trade |
| **Avoid** | — | Holding puts *through* the lockup date expecting a crash on the day | — Base rate says the date is a non-event or a bottom |

**Defining "the rollover is confirmed."** One lower high, or one close below the range low,
is a single down-leg — still consistent with Phase-1 chop. Require **≥ 2 lower highs** (each
rally peaking below the prior bounce high) **plus 2 consecutive closes below the post-IPO
range low**, or one close decisively through it. Two failed rallies say the bounce base is
weakening; a close below the range low says the range itself has given way — together they
retire the "still ranging" read. This is the price-structure replacement for the discarded
volume-expansion filter. Confirmation forfeits the first leg of the move, but because Phase 2
is a slow, low-volume bleed rather than a gap, waiting rarely costs the trade — gap risk
lives at the first earnings print, not in the decay drift.

**IV signal nuance for sub-1-year names.** IV Rank and IV Percentile are unreliable before a
stock has a 52-week IV history — a fresh IPO will read IV Rank ≈ 0 and Percentile in the low
single digits regardless of how rich IV actually is. **Watch the raw IV Index level and its
trend, not the rank.** Post-IPO IV peaks in the first days-to-weeks, crushes over months
1–3, then re-inflates into each earnings date. "Declining IV = entry signal" must be read
off the level trend.

### For a bullish / accumulate thesis

- The day-1 pop is for flippers. The accumulation window is the **dead zone (Phase 3)** —
  after premium decay has run, when a quality name is range-bound and IV has crushed.
- The re-rate trigger is the **first earnings beat the real holder base can underwrite**
  (Phase 4). Size in before it only with a fundamental thesis; do not chase the gap.
- Long options through Phases 2–3 fight both theta and the decay drift. Prefer shares, or
  wait for Phase 4 confirmation.

---

## The lockup sub-playbook

When a pipeline thesis is explicitly a lockup-expiry trade:

1. **Pull the holder composition first.** S-1 / 424B beneficial-ownership table + any
   post-IPO lock-up agreement disclosures. Strategic-heavy → the lockup is likely defused;
   downgrade or drop the trade. VC-heavy → an anticipatory bleed is plausible.
2. **Check for early-release tranches.** Many lockups release a slice on an earnings-window
   condition (e.g. N days after the first print). The "real" supply event may be earlier
   than the headline 180-day date.
3. **Trade the bleed, not the date.** If the trade survives steps 1–2: position in the
   T−6wk → T−3wk window, target the anticipatory drift, and **be flat by the date.**
4. **Watch for the forced-seller catalyst.** A regulatory / redemption / geopolitical
   development that turns a strategic holder into a motivated seller is the only thing that
   makes the unlock itself a gap. That is a *news* trade — react to the headline, do not
   pre-position for a date.
5. **Default skepticism.** Absent a VC-heavy float or a forced-seller catalyst, a pure
   lockup-date short has negative expectancy. Prefer the Phase-2 decay fade or the
   first-print event trade.

---

## 2026 structural-shift addendum

*Forward-looking rule analysis — kept separate from the empirical study above, which is
2020–2025 data. The IPO environment is changing in two ways, and they do not bind equally.*

### Bucket A — SEC deregulation *proposals* (announced, not adopted)

As of May 2026 these are proposals with comment periods running into ~July 2026. They
reshape 2027+ and act as a sentiment tailwind now; they do **not** govern the June–Q4 2026
mega-IPO wave, which prices under current rules.

| Proposal | What it does | Effect on the pattern |
|----------|--------------|-----------------------|
| **Optional semiannual reporting** (Form 10-S; proposed ~May 2026) | One half-year report may replace three 10-Qs — first structural disclosure change since the 1970s | Hits the core finding directly — *earnings is the catalyst; the first 1–2 prints carry the binary*. An opt-in name's first real print can land ~6+ months out, potentially **merging with the lockup window**. Fewer, larger, more binary catalysts; longer Phase-3 dead zones; worse for long-option holders. Large scrutinized names will likely keep voluntary quarterly 8-K releases — the option bites hardest for small caps. |
| **"IPO on-ramp" / registered-offering reform** (proposed May 19, 2026) | 60-month EGC-style accommodations; large-accelerated-filer threshold $700M→$2B; scaled disclosure; no ICFR auditor attestation for non-accelerated filers; easier shelf/follow-on eligibility regardless of float | Thinner information environment for 5 years → Phase-2 decay becomes even more flow/momentum-driven, less fundamentally anchored. Easier shelf access adds a down-catalyst the core study underweighted — **fast follow-on / secondary offerings** can dilute a hot IPO into its own strength. Weaker ICFR attestation raises accounting-surprise tail risk into the first prints. |
| **Litigation / governance pillar** | Harder securities litigation; fewer shareholder proposals | Not a price mechanic — a risk amplifier. With issuer-level mandatory arbitration now common (e.g. SpaceX routes federal securities claims to ICC arbitration), post-IPO accountability for a bad print is weaker. |

### Bucket B — structural shifts already in effect

These apply to the 2026 wave now.

**Lockup design has moved past the rigid 180-day cliff.** Current practice spans 90-day
lockups, staggered releases (e.g. 30/90/180), **price-trigger auto-release** (stock above a
threshold for N days shortens the lockup), **accelerated block-trade releases** (insiders
pre-place stock with institutions privately before expiry), and no lockup at all for direct
listings. This *reinforces* the headline finding — lockup expiry is a non-event — and makes
a fixed-date fade even worse:
- Staggered drips and block pre-placement mean **there is no cliff to fade and no single
  date to anchor on.**
- Price-trigger releases **invert the supply logic**: a strong stock unlocks early into
  demand (self-stabilizing); a weak one stays locked — the unlock turns pro-cyclical with price.
- A 30-day partial unlock pushes first supply into Phase 1, smearing the anticipatory-bleed window.

**Index inclusion has been put on a fast track.** Two rule changes, both live in 2026,
collapse the inclusion timeline the 2020–2025 comps operated under:
- **Nasdaq-100 "fast entry"** (new, effective 2026-05-01). A newly listed company whose
  market cap ranks within the **top ~40 NDX constituents (≈ $100B)** is added after just
  **15 trading days**, on 5 days' notice — waiving the usual ~3-month seasoning and
  liquidity gates. Built for the SpaceX / OpenAI / Anthropic tier.
- **S&P Dow Jones Indices "Fast Track IPO Entry."** Waives S&P's standard **12-month
  observation period** for an IPO large enough to clear the index's regular size minimum
  (S&P 500 ≈ $20B+). The lower-bar rule — it reaches well below mega-cap scale. *Worked
  example: CBRS was approved for S&P Fast Track entry effective 2026-05-25 — ~11 days after
  its IPO, at a ~$60B market cap.*

A fast-tracked IPO acquires a price-insensitive, forced index-fund bid **within weeks of
listing — inside Phase 1 or early Phase 2**, exactly the window the −40–60% premium-decay
base rate measures. A forced bid there breaks the "no natural long-term holder base has
formed yet" mechanic the decay depends on. The floor is not a force field — inclusion is a
finite, dated buy, not a perpetual bid, and index members fall all the time — but it
(a) permanently converts a slice of float to price-insensitive holders, removing the
demand-exhaustion driver of the slow bleed, and (b) injects an exogenous buying spike that
contaminates any price-structure read of the rollover. **Check a name's fast-track
eligibility before applying the Phase-2 fade.**

**The mega-cap cohort breaks the comp set.** The empirical study comps were $5–30B. The
2026 wave is a different scale — SpaceX ~$1.75–2T, OpenAI ~$850B, Anthropic ~$900B,
Stripe ~$160B, Databricks ~$130B. Four mechanics diverge:
- **Mature secondary-market price discovery** (years of Forge / EquityZen trading + tender
  offers) → smaller flipper premium → shallower Phase-1 pop and Phase-2 decay — but the
  deal can be priced *at* the inflated last private mark, leaving no cushion.
- **Index-inclusion forced bid** — see the fast-track paragraph above; at mega-cap scale
  index funds end up owning ~8–12% of the float, a structural buyer the mid-cap comps never
  had — a floor that fights Phase-2 decay.
- **Large retail allocation** (e.g. SpaceX ~30%, much of it to affiliated retail) → a
  stickier, semi-strategic holder base.
- **Staggered drip lockups** (~2–3% of float per month) → no cliff.

### The carve-out — index eligibility is the boundary, not market cap

**The −40–60% Phase-2 premium-decay base rate applies only to an IPO with no near-term
index-inclusion floor.** That figure is derived from $5–30B mid-cap AI IPOs that listed
under the *old* seasoning regime, when index inclusion was ~12 months away and Phase 2 ran
with no structural bid. Two things now lift a name out of the base rate:

- **Mega-cap scale ($100B+)** — dampens the decay through pre-matured private-market pricing
  *and* a near-immediate index bid. The original carve-out.
- **Fast-track index eligibility** — dampens it for *any* IPO large enough to be
  fast-tracked, a far lower bar than mega-cap (CBRS qualified at ~$60B). The forced index
  bid lands within weeks, inside the decay window.

The question is no longer "is this a mega-cap?" but **"will this name have a forced index
bid during Phase 2?"** If yes — by scale or by fast-track eligibility — treat the decay as
present but shallower and non-clean, do not trade the textbook Phase-2 fade off price
structure alone, and price the deal against the *core cash-generative segment* rather than
the last private round. The clean four-phase arc and the −40–60% base rate now apply only to
an IPO that is **both** sub-mega-cap **and** too small or otherwise ineligible for fast-track
index inclusion.

### How the four-phase arc shifts in 2026

| Phase | No near-term index floor | Fast-tracked or mega-cap (index floor) |
|-------|--------------------------|----------------------------------------|
| 1 — Pop & flip | Unchanged | Mega-cap: smaller pop (secondary-market price discovery already happened). Fast-track inclusion can itself spike Phase 1. |
| 2 — Premium decay | Deeper / noisier (thinner disclosure, momentum-driven); watch for fast follow-ons | Dampened *and made non-clean* by the forced index bid landing inside the decay window |
| 3 — Dead zone + lockup | Lockup even more of a non-event; dead zone longer if the name opts into semiannual reporting | Same; staggered drip lockup, no cliff |
| 4 — Re-rate | Fewer, larger, more binary prints under semiannual reporting | Same; first half-year report may merge with the lockup window |

### Process additions

1. **Map the actual lockup schedule** from the S-1 / 424B — do not assume a single 180-day
   date. Note staggered tranches, price-trigger clauses, and registration-rights /
   demand-rights dates (a separate insider-selling pathway, often ~6 months post-IPO).
2. **Watch for follow-on / secondary offerings** as a Phase-1/2 down-catalyst — easier shelf
   access makes a quick dilutive raise into strength more likely.
3. **Check fast-track index eligibility for every sub-12-month name — not just mega-caps.**
   Does the market cap clear the S&P 500 size minimum (≈ $20B+) or rank in the NDX top ~40?
   If so, model the index-inclusion date as a scheduled forced-buyer catalyst, and do not
   apply the Phase-2 decay fade without accounting for it.
4. **Check the reporting cadence** — a semiannual-reporting opt-in stretches the catalyst
   calendar and the dead zone.

---

## Applying it to CBRS

**Section under re-evaluation (2026-05-21).** S&P DJI approved CBRS for Fast Track index
entry effective **2026-05-25** (see "Index inclusion has been put on a fast track" in the
addendum). That installs a forced index-fund bid inside the Phase-2 window and directly
compromises the Phase-2-decay-fade edge asserted in point 2 below. The points below predate
that discovery; the CBRS bearish thesis is being re-scoped separately. Treat this section as
historical until revised.

CBRS (IPO 2026-05-14, priced $185, opened $350 / +89%, day-1 high $386, day-1 close $311;
~$278 as of 2026-05-21) is mid-**Phase 1** — the pop is fading but premium decay has not
begun. The pipeline thesis is a framework-reject bearish lockup-expiry play, currently
timed off "declining IV." This study materially refines that:

1. **The lockup date (~2026-11-10) is the wrong event to target.** Buying puts to expire
   just after the unlock fights the base rate — lockup day is historically a non-event or a
   relief bottom. If the unlock trade is taken at all, it is a *fade the anticipatory bleed,
   be flat by the date* trade (≈ late Sept – late Oct 2026), not a hold-through.
2. **The higher-probability, earlier bearish edge is the Phase-2 premium decay** — the +89%
   pop retracing 40–60% over roughly June–October 2026. That window opens far sooner than
   November and does not depend on lockup mechanics.
3. **The Q1 print (~Aug 2026) is the real binary** — first public earnings, with the OpenAI
   revenue start, the guided gross-margin step-down, and concentration disclosure all
   landing at once. A defined-risk bearish structure expiring just after that date is a
   cleaner catalyst trade than the lockup.
4. **Holder composition is decisive and currently ambiguous.** MBZUAI (62%) and G42 (24%)
   are strategic, sovereign-linked holders — the ARM precedent says a strategic-heavy float
   *defuses* the lockup. The bear case for the unlock therefore rests on the VC backers and
   founders/employees selling, *and* on CFIUS / export-control pressure converting G42 /
   MBZUAI into forced sellers. Resolve this before sizing any lockup-specific trade: if
   G42 / MBZUAI publicly reaffirm long-term-holder intent, the lockup loses most of its teeth.
5. **IV trajectory:** CBRS IV Index ≈ 98% with IV Rank ≈ 0 / Percentile ≈ 5% — the rank and
   percentile are meaningless on a 5-day-old stock. Track the **IV Index level trend**, not
   the rank, as the entry-timing signal.

**Net:** the strongest CBRS bearish expressions are the Phase-2 decay fade (months 1–4) and
the Q1-print event trade (~Aug 2026) — not a put position held into the November lockup.
The lockup is at most a conditional anticipatory-bleed trade, gated on holder composition.
