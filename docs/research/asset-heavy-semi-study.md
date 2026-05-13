# Asset-Heavy Semiconductor IPO Study

**Status:** 4 of 4 reviewed
**Started:** 2026-05-12
**Owner:** Claude + Lingnan

## Purpose

Identify financial and qualitative signals — observable in real-time at S-1 — that separated successful asset-heavy semiconductor IPOs from mediocre and failed ones. Tests whether the existing `pre-profit-growth-framework.md` (designed for SaaS / NWC pre-profit IPOs) generalizes to semis, and if not, what semi-specific gates are needed.

Output feeds either (a) a third "Semi" path added to the existing framework's capital-structure prerequisite, or (b) a separate `asset-heavy-semi-framework.md`.

## Cohort constraints

The natural cohort is small. Most successful asset-heavy semi IPOs (TSM 1997, INTC 1971, AMD 1972, AMAT 1972) predate EDGAR HTML filings and aren't text-extractable. The empirically studyable population skews toward:

- Recent IPOs (2008-onward, when EDGAR mandate took hold)
- Failures (rich data because S-1 + post-mortem analyses exist)
- Specialty / fabless plays (lower capital burn means more reach the public market)

True foundries that IPO while pre-profit are rare — most are absorbed by sovereigns or capital before going public.

## Cohort

| Tier | Name | Filing | Sub-type |
|---|---|---|---|
| Mediocre | **GFS** (GlobalFoundries) | 2021-10-29 424B4 | Foundry / IDM |
| Recent success | **ALAB** (Astera Labs) | 2024-03-21 424B4 | Fabless specialty |
| Failure | **GTAT** (GT Solar / GT Advanced Technologies) | 2008-07-24 424B4 | Specialty equipment |
| Live application | **CBRS** (Cerebras Systems) | 2026-05-11 S-1/A | AI systems / fabless hybrid |

**Out-of-scope (data unavailable but worth noting):**

- TSM 1997 ADR — F-6 depositary registration, not F-1 prospectus; 1997 IPO underlying entity is Taiwanese
- INTC 1971, AMD 1972, AMAT 1972 — all predate EDGAR HTML filings
- Wolfspeed (was Cree) — original Cree 1993 IPO was an LED business; SiC pivot happened post-IPO so not testable as an "asset-heavy IPO" against the framework
- Tilera, Calxeda, Wave Computing — never IPO'd publicly; failed in private

## Methodology

### Snapshot timing

Three observation points per company:

1. **S-1 / IPO** — most recent disclosed full fiscal year + interim period
2. **+2yr post-IPO** — captures whether IPO-stage trends held up under public-market scrutiny
3. **Outcome stage:**
   - Success: 1-3 years before first GAAP profit OR sustained margin expansion
   - Mediocre: 2-3 years post-IPO, stock at or below IPO price with no clear inflection
   - Failure: 1-3 years before terminal event (BK, fire-sale acquisition, >80% drawdown)

For names where the IPO is recent (CBRS, ALAB), the "outcome stage" is partially or fully unobservable — this is itself a study finding (we're applying a framework to a present-tense decision, not a backtested one).

### Variables tracked (semi-specific extension)

Same growth-quality and capital-discipline variables as `pre-profit-growth-study.md`, plus:

**Semi-specific manufacturing economics**
- Process node generation at IPO (leading-edge, mainstream, trailing)
- Wafer capacity utilization %
- Single-fab vs multi-fab footprint
- Capex per wafer of capacity (where disclosable)
- IFRS vs GAAP reporting (foundries often IFRS)

**Supply-chain commitments**
- Take-or-pay agreements (which side: customer or supplier)
- Wafer supply / capacity reservation contracts
- Customer prepayments
- Long-term supply agreements with foundries (for fabless designers)

**Government / sovereign exposure**
- CHIPS Act or equivalent grants disclosed
- Sovereign customer concentration (G42, MBZUAI, etc.)
- Sovereign owner / shareholder (Mubadala for GFS, ADIA, etc.)
- Export control exposure (BIS, Department of Commerce)

**End-market / customer mix**
- Top-customer % (semis tolerate higher concentration than software — TSM had Apple at 25%+ for years)
- End-market diversity (auto / mobile / data center / industrial / IoT)
- Foundry vs fabless customer base

### Per-name deliverable

1. One-paragraph context (what they did, IPO date, outcome to date)
2. Three-snapshot table — same shape as the existing study with semi-specific rows added
3. Narrative at each stage (bull and bear case **at the time**, not in hindsight)
4. Pre-profit-growth-framework gate-by-gate dry run — does the existing framework correctly classify them?
5. Signal observations — which gates discriminated, which misled, which were unreadable
6. Data quality note

### Synthesis (built incrementally)

After all 4 reviews, synthesize:
- Did the existing framework correctly classify each name?
- Which gates needed semi-specific recalibration (e.g., 10% customer concentration cap is too strict for semis)?
- What new gates surfaced (capacity reservation, sovereign exposure, process node)?
- Conclusion: extend the existing framework with a Semi path, or build a separate framework?

---

## Reviews

### #1 — GFS (GlobalFoundries)
*Reviewed 2026-05-12*

**Context.** GFS is a "pure-play" semiconductor foundry — manufactures chips designed by other companies. Spun out of AMD in 2009, then merged with Chartered Semiconductor (Singapore) in 2010 and IBM Microelectronics (US) in 2014, all funded by Mubadala (Abu Dhabi sovereign wealth fund). Reported under IFRS. Strategic repositioning began 2018 to abandon leading-edge competition (sold ASIC business, exited 7nm race) and focus on differentiated trailing-edge processes (FD-SOI, RF SOI, automotive-grade silicon). IPO'd Oct 28, 2021 at $47 (within range), opened ~$47, closed day 1 at $46. Outcome to date: stock peaked ~$75 in late 2021, traded mostly $40-50 since; remains money-losing on a GAAP basis through 2024 despite the post-COVID semi cycle. Mediocre by IPO standards but survived — without Mubadala backing and the strategic IBM cash payment, would likely have failed.

**Three-snapshot table** (all $ in millions; IFRS; FY = calendar year)

| Metric | FY2018 (S-1 baseline-3) | FY2020 (S-1 baseline-1) | 1H2021 (interim, latest at IPO) |
|---|---:|---:|---:|
| Net revenue | $6,196 | $4,851 | $3,038 |
| YoY growth | — | -16.6% | +12.6% (vs 1H20) |
| Gross profit (loss) | -$450 | -$713 | +$330 |
| Gross margin | -7.3% | -14.7% | +10.9% |
| R&D | $926 | $476 | $235 |
| R&D % revenue | 15.0% | 9.8% | 7.7% |
| SG&A | $453 | $445 | $293 |
| Restructuring + impairment | $694 | $23 | $0 |
| Loss from operations | -$2,523 | -$1,656 | -$198 |
| Operating margin | -40.7% | -34.1% | -6.5% |
| Net loss | -$2,774 | -$1,351 | -$301 |
| Customer concentration | Top 10 customers ~70% of revenue (S-1 risk factors) | — | — |
| Capex (cash flow) | not yet extracted | not yet extracted | not yet extracted |
| Process node range | 12nm (leading at IPO) → 180nm | same | same |
| Wafer fab footprint | 5 fabs: Malta NY (300mm), Dresden DE (300mm), Singapore (200/300mm) | same | same |
| Sovereign owner | Mubadala (~88% post-IPO) | same | same |

**Narrative at the time.**

*Bull case (Oct 2021):* Foundry industry consolidating to 3 leading-edge players (TSMC, Samsung, Intel). GFS's strategic repositioning out of leading-edge competition is sensible — focus on the larger ($54B SAM) "pervasive semiconductor" market for automotive, industrial, communications. Multi-year customer LTAs with capacity reservations provide revenue visibility. 1H2021 gross margin flipping positive shows the restructuring is working. Post-COVID semi shortage means foundry capacity is genuinely scarce. Mubadala backing + IBM cash payment removes capital risk. CHIPS Act tailwind for non-Asian foundries.

*Bear case at the time:* Revenue declined 22% from 2018→2020 (even pre-COVID). R&D cut nearly in half ($926M → $476M), which is the wrong direction for a tech company. $694M of restructuring/impairment charges in 2018 alone signals operational instability. Gross margin had been negative for years; "1H21 positive" is one half-year of data. Mubadala selling shares = dilution overhang. Foundry capex intensity remains structurally high — cap-light pivot is real but not enough to escape capital-cycle pain. Customer concentration risk: top 10 = 70%+ of revenue with long-term commitments that lock both upside and downside.

**Pre-profit-growth-framework gate-by-gate dry run.**

| Gate | Pass / Fail | Notes |
|---|---|---|
| Pre-check: TTM revenue ≥ $100M | ✓ | $4.85B FY2020 |
| Pre-check: Op income ≤ 0 | ✓ | -$1.66B FY2020 (yes, it's pre-profit by this gate) |
| Pre-check: ≥1 audited fiscal year | ✓ | 3 years disclosed |
| Disqualifier: Invented non-GAAP metric | ⚠ | Adjusted EBITDA / Adjusted gross profit excludes impairments + restructuring + share-based comp. Defensible by IFRS norms, but non-trivial adjustments. Borderline. |
| Disqualifier: Self-dealing | ✗ none | Mubadala is owner not vendor; no insider transactions flagged |
| Disqualifier: Sharp recent-year deterioration | ✗ TRIGGERED | GM worsened from -7.3% (2018) → -9.2% (2019) → -14.7% (2020). Three consecutive years of deterioration > 5pp. **AUTOMATIC REJECT per framework.** |
| Disqualifier: Self-disclosed structural unprofitability | ✗ none | Counter-narrative is "improving" trajectory |
| Cap structure: Software path (GM ≥70%) | ✗ | GM is negative |
| Cap structure: NWC path (GM ≥15%, repeat ≥40%) | ✗ | GM negative; foundries don't disclose "repeat customer rate" — they have take-or-pay LTAs which is functionally similar but doesn't fit the gate |
| Hard req: Customer concentration ≤10% | ✗ | Top 10 ~70%; top customer % not disclosed but inferable as material |
| Hard req: Concentration trajectory | unreadable | Not disclosed in trend form |
| Hard req: Operating history ≥3 years | ✓ | Has 12 years of operating history at IPO |
| Hard req: Pre-IPO capital / TTM revenue ≤5x | ✗ | Mubadala has invested >$25B since 2009; >$25B / $4.85B ≈ 5x+ |
| Hard req: Off-balance-sheet commitments ≤3x revenue | unknown | Not extracted in spike |

**The framework rejects GFS at the disqualifier step (sharp deterioration in most recent year)**, then again at the cap-structure prereq (neither path passes), then again at the customer-concentration hard requirement. **Three independent gates flag this name.**

**Signal observations.**

| Signal | Discriminating? | Notes |
|---|---|---|
| Sharp YoY revenue decline | ✓ strong | Clear quantitative red flag visible at S-1 |
| R&D cut in half over 3 years | ✓ strong | Tech companies cutting R&D is a structural warning, not a cost-discipline win |
| Gross margin negative for 3 years | ✓ strong | Foundries should have positive GM at scale; persistent negative GM means utilization or pricing problems |
| Sovereign owner | misleading | Mubadala backing kept GFS solvent through years that would have killed a public-market company. The framework can't reward this — and shouldn't, because it's not a unit-economics signal |
| 1H21 GM flip positive | misleading | Single half-year inflection on a 3-year decline is not statistically meaningful at IPO |
| "Strategic repositioning" narrative | misleading | "We pivoted from a money-losing business to a different money-losing business" — investors who took this at face value got mediocre returns |
| Customer concentration disclosure | semi-specific quirk | Foundries always have concentrated customer bases. The 10% gate is too strict; needs a sector-specific threshold (maybe 25-30% top customer for semis) |
| Capex intensity disclosure | partially extractable | Foundries disclose total capex but the framework wants capex/revenue — need to compute |

**Data quality.** Strong on income statement (extracted directly from the F-1 summary financials table). Weak on capex/cash-flow specifics — would need to read the cash-flow narrative section in MDA to populate. Customer concentration top-10 = 70% comes from risk factors; top-1 / top-3 / trajectory not disclosed in the prose we extracted. Capacity utilization % was disclosed in MDA but not extracted in this pass.

**Outcome to date (5/2026, ~4.5 years post-IPO).** Stock at ~$40, below $47 IPO price. Revenue grew to ~$7B by FY2024 driven by post-COVID semi cycle, then softened as automotive demand cooled. GAAP losses persist. Mubadala has reduced ownership but remains majority shareholder. Strategic positioning ("differentiated trailing edge") remains the bull thesis but has not produced multiple-expanding margin growth. **Framework verdict was correct: clear reject, mediocre outcome.** The mediocre-not-failure outcome is attributable to sovereign backing and CHIPS Act tailwind, neither of which the framework should credit.

---

### #2 — GTAT (GT Solar / GT Advanced Technologies)
*Reviewed 2026-05-13*

**Context.** GTAT (then named GT Solar International, Inc.) made specialized manufacturing equipment for the solar PV industry: directional solidification systems (DSS units — furnaces for casting solar wafers) and chemical vapor deposition reactors (CVD — for polysilicon production). Founded 1994 as GT Equipment Technologies; acquired Jan 2006 by GFI Energy Ventures + Oaktree (PE buyout); IPO'd Jul 24, 2008 at $16.50. The IPO was a pure secondary — selling shareholder was GT Solar Holdings LLC; the company itself received zero proceeds. Insiders also took a $90M dividend in June 2008, immediately before the IPO. Outcome: stock collapsed 80%+ within months in the 2008-09 financial crisis + solar bust. Recovered partially with the November 2013 Apple sapphire-glass supply deal. Apple terminated the deal Oct 2014; GTAT filed Chapter 11 the same week. Total return from IPO to bankruptcy: -95%. Canonical asset-heavy semi failure.

**Three-snapshot table** (all $ in millions; US GAAP; fiscal year ends March 31)

| Metric | FY2006 (combined w/ Predecessor) | FY2007 | FY2008 (latest at IPO) |
|---|---:|---:|---:|
| Revenue | $46.8 | est. $74 (implied by CAGR) | $244.1 |
| YoY growth | — | ~58% | +230% |
| Gross margin | not extracted | not extracted | est. >30% (PV equipment norms) |
| R&D expense | $1.2 | $1.8 (FY ended Mar 2007) | $3.8 (FY ended Mar 2008) |
| R&D % revenue | 2.6% | 2.4% | 1.6% |
| **Operating profit?** | **negative ($21.8M net loss)** | data not extracted | **POSITIVE — $36.1M net income** |
| Order backlog (period-end) | not disclosed | $399M | **$1,307M** |
| Backlog as multiple of TTM revenue | — | ~5x | ~5.4x |
| **Top customer %** | — | — | **62% (1 customer)** |
| **Top 3 customers %** | 64% | 70% | not split out, but $769M of $1,307M backlog (59%) is from 3 customers |
| **DSS units % of revenue** | 72% | 85% | **86%** |
| End-market dependency | Solar PV (subsidy-driven) | same | same |
| Capex / revenue | not extracted | not extracted | low (outsourced manufacturing model — disclosed) |
| Sponsor ownership | GFI + Oaktree (private) | same | ~80% post-IPO retained |
| Pre-IPO dividend to insiders | — | — | **$90M (June 2008)** |
| Use of IPO proceeds | n/a (secondary only) | n/a | n/a — sponsor exit |

**Narrative at the time.**

*Bull case (Jul 2008):* Solar industry growing 47% CAGR. Polysilicon shortage driving CVD reactor demand. Backlog 5x trailing revenue with mostly long-dated CVD contracts ($659M, with ~12-18 month delivery). Already GAAP-profitable — $36M net income FY2008 vs $22M loss FY2006. Outsourced manufacturing keeps capex light. Turnkey solutions create high switching costs. Established relationships with leading solar manufacturers including those building new facilities in China. Government incentive programs accelerating end-customer demand.

*Bear case at the time:* The S-1 itself disclosed three structural concerns plainly:
1. **62% of revenue from a single customer in FY2008** (concentrating up from 64% top-3 in FY2006). The risk-factor language is explicit: "we depend on a small number of customers."
2. **86% of revenue from a single product (DSS units)** — concentrating, not diversifying. Product diversification narrative was aspirational, not realized.
3. **End-customer demand is subsidy-driven** ("government incentive programs designed to encourage the use of renewable energy sources, including solar power"). The risk factors devote a section to subsidy expiration risk.

Plus structural IPO concerns:
4. **PE secondary-only IPO** — company gets no capital; sponsor monetizes. Combined with the $90M pre-IPO dividend, this is a "PE exit, not growth financing" pattern.
5. **Polysilicon shortage was the bull case** — but the same shortage was driving incumbent producers to add capacity. Once that capacity came online, the polysilicon spot price would crater (and did, ~80% drop 2008-2009).
6. **Customer financial fragility flagged in S-1**: "many of our customers are at an early stage and many are dependent on the equity capital markets to finance their purchase of our products." Read: the backlog is fragile because customers may not survive to take delivery.

**Pre-profit-growth-framework gate-by-gate dry run.**

| Gate | Pass / Fail | Notes |
|---|---|---|
| **Pre-check: Op income ≤ 0** | **✗ FAILS — already GAAP-profitable** | Net income +$36.1M FY2008. **OUT-OF-SCOPE** for the speculative-growth framework. Per `decision-framework.md`, this routes to Accumulate or Defined-risk-exposure tier. |

The framework correctly excludes GTAT at the pre-check. But this means the framework's *gates* don't themselves discriminate the failure — they never get evaluated. To compare:

If we had ignored the pre-check and run the gates anyway:

| Gate | Pass / Fail | Notes |
|---|---|---|
| Disqualifier: Sharp recent-year deterioration | ✗ none | Revenue +230% YoY; margins improving |
| Disqualifier: Self-disclosed structural unprofitability | ✗ none | Revenue and earnings both growing |
| Disqualifier: Self-dealing | ⚠ borderline | $90M pre-IPO dividend to PE sponsors is not self-dealing per se but pattern flag |
| Disqualifier: Invented non-GAAP metric | ✗ none | Standard GAAP reporting |
| Cap structure: Software path (GM ≥70%) | ✗ | Equipment maker; GM ~30%, not 70% |
| Cap structure: NWC path (GM ≥15%, repeat ≥40%) | ⚠ | GM probably passes; "repeat customer" depends on how multi-order CVD reactor contracts are interpreted |
| **Hard req: Customer concentration ≤10%** | **✗ CATASTROPHIC FAIL — 62% from one customer** | One of the worst concentration disclosures in the cohort |
| **Hard req: Concentration trajectory** | **✗ FAILS — concentrating** | Top concentration moving FROM diffuse 3-customer 64% TO single-customer 62% |
| Hard req: Operating history ≥3 years | ✓ | 14 years since founding |
| Hard req: Pre-IPO capital / TTM revenue ≤5x | ✓ probably | PE buyout in Jan 2006 at modest multiple |
| Hard req: Off-balance-sheet commitments ≤3x revenue | unclear | Backlog isn't a balance-sheet item but is 5x revenue — semi-relevant |
| Soft: Multi-product expansion | ✗ | 86% DSS; concentrating not diversifying |

**The framework would reject GTAT on customer concentration alone, twice over (level + trajectory).** The fact that the pre-check excluded GTAT is procedurally correct but means the gate verdict comes via different routing.

**Signal observations.**

| Signal | Discriminating? | Notes |
|---|---|---|
| Customer concentration ≥50% from one customer | ✓ extremely strong | Visible at S-1; same pattern that killed GTAT in 2014 (Apple = ~80% by then) |
| Concentration trajectory (3 customers → 1 customer) | ✓ strong | Forward-looking signal that the framework does capture |
| Single-product dependency >80% | ✓ strong | The bull case is "we'll diversify" — but the trend was the opposite |
| End-market subsidy dependency | ✓ strong | Solar 2008-2012 is the canonical example of "subsidy expiration cratering a whole sector" |
| Already GAAP-profitable at IPO | misleading without sector context | In semis, profitable IPO + customer concentration ≥50% may actually be MORE dangerous than pre-profit IPO + diversified base, because the profit creates false comfort |
| 5x backlog coverage | misleading | Order backlog isn't binding revenue. Many GTAT customers were "early-stage" with capital-market financing risk per S-1 |
| PE secondary-only IPO + pre-IPO dividend | ✓ moderate | Procedural pattern: sponsor exit, not growth capital. Combined with the $90M dividend, the IPO didn't strengthen the company |
| Outsourced manufacturing (capex-light) | misleading | Looked like a positive but didn't help when end-market demand collapsed — capex-light didn't save them |

**Gate-calibration findings for the framework.**

1. **Customer concentration**: GTAT validates that **>50% from a single customer is a near-automatic failure signal**, especially when that customer is in a fragile end-market. Even with the 10% gate, a >50% disclosure is so far past the threshold that it should trigger the strongest possible warning.
2. **Subsidy / end-market exposure**: The framework currently has no explicit gate for "end-customer demand is policy-driven." For semis specifically, this needs to be added — solar (GTAT, Solyndra), EV credits (RIVN, NKLA), and CHIPS-Act-dependent foundries (GFS to a degree) all share this fragility.
3. **Already-profitable-at-IPO names need their own framework**, not the speculative-growth one. The speculative-growth framework's pre-check is correct to exclude them, but the existing decision framework's "Accumulate" and "Defined-risk" tiers don't have specific guidance for **profitable-but-fragile single-customer hardware companies**. This is an open framework gap that GTAT exposes.
4. **PE secondary-only IPO** is a procedural yellow flag worth tracking. Not necessarily disqualifying, but the combined pattern (sponsor exit + insider dividend + no IPO proceeds) means the IPO isn't strengthening the underlying business.

**Data quality.** Strong on customer concentration, product mix, and backlog (all explicitly disclosed in risk factors and MDA). Strong on net income trajectory (in prospectus summary). Weak on capex/cash-flow detail — would need balance sheet section. Weak on quarterly trajectory within FY2008 (we have annual data only). Sufficient for the framework verdict.

**Outcome to date (filed 7/24/2008; bankrupt 10/6/2014, ~6 years post-IPO).** Stock peaked early near $18 (close to IPO), collapsed to <$2 in late 2008 in the financial crisis + solar bust. Recovered briefly to ~$10 in 2013-2014 on the Apple sapphire deal announcement. Apple terminated the deal Oct 2014; GTAT filed Chapter 11 within a week at ~$0.80/share. Restructured as smaller "GTAT IP Holdings"; common shareholders wiped out. **The framework verdict (multiple-gate failure on concentration + trajectory + product dependency, plus the structural subsidy exposure) was correct.** The 2014 Apple termination was the trigger event but the underlying fragility — single-customer dependency, single-product dependency, capital-market-dependent customers — was disclosed plainly in the 2008 S-1.

---

### #3 — ALAB (Astera Labs)
*Reviewed 2026-05-13*

**Context.** ALAB is a fabless semiconductor company designing connectivity ICs for AI infrastructure: PCIe retimers (Aries), CXL memory expansion (Leo), and Ethernet smart cable modules (Taurus). All chips are manufactured at TSMC. Founded October 2017 by ex-Texas Instruments engineers; backed by Sutter Hill Ventures + Intel Capital + Fidelity. Sells primarily through distributors (notably Wiwynn/Foxconn ODMs) to hyperscaler end customers (Microsoft, Meta, Google, AWS) and system OEMs (NVIDIA reference designs, Dell, Supermicro). IPO'd Mar 21, 2024 at $36 (above the raised $27-30 range), opened ~$52, closed first day at $62 (+72%). Outcome to date (~14 months post-IPO): stock peaked >$130 in 2024, traded volatile $80-130 range through 2025, currently in user's pipeline as a "Phase 1c accelerating" name. **Live success-in-progress, not yet a fully validated winner.**

**Three-snapshot table** (all $ in thousands; US GAAP; FY = calendar year)

| Metric | FY2022 (S-1 baseline-1) | FY2023 (latest at IPO) |
|---|---:|---:|
| Revenue | $79,872 | $115,794 |
| YoY growth | — | +45% |
| Gross profit | $58,681 | $79,827 |
| **Gross margin** | **73.5%** | **68.9%** |
| R&D expense | $73,711 | $73,407 |
| **R&D % revenue** | **92.3%** | **63.4%** |
| S&M | $24,407 | $19,992 |
| G&A | $20,757 | $15,925 |
| Operating loss | -$60,194 | -$29,497 |
| Operating margin | -75.4% | -25.5% |
| Net loss | -$58,345 | -$26,257 |
| **Operating cash flow** | **-$35,900** | **-$12,700** |
| OCF margin | -45% | -11% |
| Capex | $3,900 | $2,800 |
| Capex / revenue | 4.9% | 2.4% |
| **Top customer (distributor)** | **81.7%** | **37.0%** |
| **Top 3 customers** | 95.7% (1 dist + 1 cust) | **79.3%** |
| Concentration trajectory | — | **Deconcentrating** (-44pp top customer) |
| End-customer base | Hyperscalers via ODM/distributor | same |
| Cash + marketable securities | (post-Series D ~$200M) | $149.3M |
| Manufacturing model | Fabless, all wafers via TSMC | same |

**Narrative at the time.**

*Bull case (Mar 2024):* Pure-play AI infrastructure connectivity at the moment hyperscaler capex is inflecting upward. Mission-critical product (without retimers, PCIe Gen 5/6 signals don't reach across multi-rack AI training systems). 300+ design wins disclosed at S-1 — broad penetration of customer base. Revenue +45% with operating loss compressing fast (-75% margin → -26%). OCF approaching break-even. Gross margin 69-74% — clean Software-path semi (asset-light fabless). Customer concentration deconcentrating rapidly (top customer 82% → 37% in one year), suggesting the IPO captured a transition from "single anchor customer" to "broad hyperscaler adoption." Trusted relationships with NVIDIA, AMD, Intel as design partners. Industry standards-based products (PCIe, CXL, Ethernet) avoid proprietary lock-in risk on the customer side.

*Bear case at the time:* Top customer (distributor) still at 37% — well above any reasonable concentration threshold. Distributor concentration may mask end-customer concentration: the underlying hyperscaler buyer is unknown but plausibly NVIDIA-driven (most retimer demand is AI accelerator interconnect). Single-product dependency: Aries (PCIe retimer) is the dominant SKU; Leo (CXL) and Taurus (Ethernet) are early stage with limited revenue contribution. **Connectivity is a layer that gets absorbed**: when hyperscalers build custom silicon (Google TPU v5, AWS Trainium 2, Microsoft MAIA), they often integrate the connectivity function rather than buying discrete retimers. Astera's relevance depends on the rate of in-house connectivity integration trailing the rate of new accelerator deployment. R&D at 63% of revenue is high but explainable for early-stage fabless; if revenue scaling slows, this becomes a margin trap. Vendor lock-in to TSMC for leading-edge nodes (Aries built on advanced process). IPO timing perfectly captures peak AI sentiment — "AI tax" applied to the multiple.

**Pre-profit-growth-framework gate-by-gate dry run.**

| Gate | Pass / Fail | Notes |
|---|---|---|
| Pre-check: TTM revenue ≥ $100M | ✓ | $115.8M FY2023 |
| Pre-check: Op income ≤ 0 | ✓ | -$29.5M FY2023 |
| Pre-check: ≥1 audited fiscal year | ✓ | 2 years disclosed |
| Disqualifier: Sharp recent-year deterioration | ✗ none | Margins improving fast |
| Disqualifier: Self-disclosed structural unprofitability | ✗ none | Path to break-even articulated |
| Disqualifier: Self-dealing | ✗ none | Customer warrants are conventional revenue-rebate accounting |
| Disqualifier: Invented non-GAAP metric | ✗ none | Standard reporting |
| **Cap structure: Software path** | **✓ PASSES** | GM 68.9% (just under 70%, borderline) / 73.5% (FY22). Capex/rev 2.4-4.9% ≪ 10%. OCF margin improving from -45% → -11%, clear path to positive. |
| Hard req: Customer concentration ≤10% | **✗ FAILS** | Top distributor 37%; multiple customers >10% |
| Hard req: Concentration trajectory | **✓ PASSES — deconcentrating** | Top went from 81.7% → 37.0%; trajectory is the right direction |
| Hard req: Operating history ≥3 years | ⚠ borderline | 6+ years since founding but commercial scale only since 2020 (Aries launch) — 4 years of meaningful operations |
| Hard req: Pre-IPO capital / TTM revenue ≤5x | ✓ probably | ~$200M raised pre-IPO / $115.8M = 1.7x — good ratio |
| Hard req: Off-balance-sheet commitments ≤3x revenue | ✓ probably | Fabless model = no fab leases or capex commitments |
| Hard req: NRR ≥120% (software path) | unreadable | Hardware companies don't disclose NRR; design wins (300+) is the rough analog but not directly comparable |
| Soft: Cash flow inflection (CFO+ within 24 months) | ✓ likely | -$35.9M → -$12.7M trajectory implies CFO+ in 2024 |
| Soft: S&M efficiency ≥0.5x | ✓ | Revenue grew $35.9M; S&M was $20M (and shrunk YoY) — efficiency >1.0x |
| Soft: Multi-product expansion | ⚠ borderline | Aries dominant; Leo/Taurus articulated but early — articulation present, traction limited |
| Soft: Founder still at company | ✓ | CEO Jitendra Mohan (founder) at IPO |
| Soft: Operating margin trajectory improving 3+ years | ⚠ only 2 years disclosed | -75% → -26% across 2 years; one more year needed for "3 consecutive" |

**Verdict per framework:** **REJECT on customer concentration hard requirement (10% rule).** Cap structure passes (Software path); soft signals 3-4/5 favorable; trajectory positive. But the strict 10% concentration gate is failed.

**Critical observation:** ALAB is the cohort's clearest example of an "acceptable false negative" — the framework rejects but the name is performing well post-IPO. Per the framework doc's own NVDA/TWLO/ROKU cluster note, this is expected behavior. The framework's bias-to-rejection means we'd miss ALAB until the next 10-K showed concentration normalizing further.

**Signal observations.**

| Signal | Discriminating? | Notes |
|---|---|---|
| Concentration trajectory (-44pp in 1 year) | ✓ very strong | Direction matters more than level. ALAB and GTAT both had >50% concentration; trajectory is opposite |
| End-customer durability | ✓ strong (qualitative) | Hyperscalers (creditworthy, structural demand) vs solar manufacturers (capital-market dependent). Not directly disclosed as a metric, but inferable from customer segment language |
| Gross margin ≥70% in fabless semi | ✓ strong | Distinguishes "software-grade economics" from equipment / commodity silicon |
| R&D intensity 60-90% | misleading without context | Looks alarming on its own but is structurally normal for early-stage fabless hardware (heavy IP costs upfront, scale dilutes the ratio) |
| Capex /rev <5% | ✓ strong | Confirms genuinely fabless model; distinguishes from "fab-lite" or asset-heavy specialty (GFS, GTAT) |
| OCF margin improving 30+ pp YoY | ✓ strong | Clean signal; better than absolute level for early-stage |
| Distributor counts as customer (look-through rule) | semi-specific complication | Strict look-through inflates concentration vs end-user reality. Hyperscalers buying through Wiwynn/Foxconn isn't the same risk as Pets.com buying through Petsmart |
| 300+ design wins | ✓ moderate | Hardware-specific scaling proxy; partial substitute for NRR which doesn't apply |
| Industry-standards product (PCIe/CXL) | ✓ moderate (qualitative) | Lower lock-in risk vs proprietary; expands TAM beyond single-vendor ecosystems |

**Gate-calibration findings for the framework.**

1. **Customer concentration 10% rule is too strict for semis.** Both ALAB (success-in-progress) and GTAT (canonical failure) trip the 10% gate. The discriminating variable is **trajectory** + **end-customer durability**, not the level. Suggested recalibration: either raise the static threshold to 25-30% for semis, or weight concentration trajectory equally with concentration level.
2. **Distributor look-through needs nuance.** The framework's "look-through to whoever physically pays" rule, applied strictly, treats ALAB selling through Wiwynn-to-Microsoft as a distributor concentration failure. But the end customer is creditworthy and has structural demand. Suggested rule: when distributor flows to disclosed end-customer hyperscalers, treat distributor concentration as an attenuated signal (apply ~50% weight) rather than a hard fail.
3. **R&D intensity should be evaluated as a trajectory, not a level.** ALAB at 92% looks scary, 63% is high but normal for hardware, and probably 35-40% at maturity. The discriminating signal is whether it's *trending down with revenue scaling*, not the absolute number.
4. **Hardware-specific NRR substitute**: 300+ design wins (or design-win growth rate) is a reasonable hardware substitute for software NRR. The framework should acknowledge this as the equivalent metric for fabless semis.
5. **OCF improvement rate** (here, +34pp YoY) is a more powerful signal than OCF level for early-stage semis. The framework currently asks for "CFO+ within 24 months" — ALAB's trajectory makes this near-certain even at -11% margin in the latest year.

**Data quality.** Excellent on income statement, OCF, capex, customer concentration (all disclosed quantitatively). Strong on product mix qualitative discussion. Weak on direct end-customer disclosure (distributor masks the actual hyperscaler buyer). NRR not disclosed (hardware companies don't typically report it). Sufficient for framework verdict.

**Outcome to date (filed 3/21/2024; ~14 months post-IPO).** Stock peaked >$130 in 2024, currently in $80-130 range. Revenue scaling rapidly (estimated >$300M FY2024, on track for $500M+ FY2025). User has it in pipeline as Phase 1c accelerating. Customer concentration likely continued to dilute as hyperscaler base broadened. **Framework verdict (reject on 10% concentration) is technically correct per the rule but is the canonical "acceptable false negative" pattern — name has performed well despite the rejection signal.** This is the live evidence that the 10% gate needs sector-specific recalibration for semis.

---

### #4 — CBRS (Cerebras Systems)
*Reviewed 2026-05-13*

**Context.** CBRS designs and sells wafer-scale AI chips (the WSE — currently 3rd generation on TSMC 5nm) and operates an AI inference cloud built on its own chips. Founded 2016 by Andrew Feldman (CEO, ex-SeaMicro/AMD); built three product generations (WSE-1 16nm, WSE-2 7nm, WSE-3 5nm). Originally filed S-1 September 2024; IPO delayed by 18 months due to CFIUS review of an attempted G42 (UAE) equity investment. CBRS withdrew the CFIUS notice in March 2025; G42 ended up NOT taking equity (only commercial warrants for product purchases). Re-filed S-1 April 2026; latest amendment May 11, 2026. **Live application — not yet IPO'd as of this review date.** January 2026 announced a $20B+ multi-year MRA with OpenAI for 750MW of dedicated AI compute, including a $1B working capital loan from OpenAI. March 2026 announced AWS partnership for inference distribution.

**Three-snapshot table** (all $ in thousands; US GAAP; FY = calendar year)

| Metric | FY2024 (S-1 baseline-1) | FY2025 (latest at amended S-1) |
|---|---:|---:|
| Total revenue | $290,252 | $509,991 |
| YoY growth | — | +75.7% |
| — Hardware | $211,965 (73%) | $358,440 (70%) |
| — Cloud / services | $78,287 (27%) | $151,551 (30%) |
| Gross profit | $122,738 | $199,071 |
| **Blended gross margin** | **42.3%** | **39.0%** |
| — Hardware GM | 35.2% | **42.9%** (improving) |
| — Cloud GM | **61.4%** | **29.9%** (collapsed — capacity ramp) |
| R&D | $158,234 | $243,319 |
| R&D % revenue | 54.5% | 47.7% |
| S&M | $20,980 | $70,645 |
| S&M % revenue | 7.2% | 13.8% (scaling fast) |
| G&A | $44,962 | $30,969 |
| Operating loss | -$101,438 | -$145,862 |
| Operating margin | -34.9% | -28.6% |
| **OCF** | **+$451,978** (with prepayments) | **-$10,050** |
| Capex | not extracted | not extracted |
| Net loss | -$481,602 (incl. preferred revaluation) | +$237,827 (revaluation gain) |
| **Customer concentration: top customer** | **G42 = 85.0%** | **MBZUAI = 62.0%** |
| 2nd customer | — | G42 = 24.0% |
| **Combined UAE/sovereign exposure** | **85.0%** | **~86% (G42 + MBZUAI both UAE-affiliated)** |
| New mega-customer | — | OpenAI MRA Dec 2025: $20B+ multi-year, $1B working capital loan |
| Pre-IPO capital raised | ~$720M equity + $1B OpenAI loan = ~$1.72B | same |
| Pre-IPO capital / TTM revenue | — | 3.4x |
| Voting structure | Multi-class | Multi-class — existing holders = 99.2% voting power post-IPO; directors/officers = 50.9% |
| Founder still CEO | ✓ Andrew Feldman | ✓ |
| Manufacturing model | Fabless via TSMC 5nm | same |
| Cash + equivalents (EOY) | not extracted | $701,706 |

**Narrative at the time.**

*Bull case (May 2026):* AI compute demand inflecting; CBRS has differentiated wafer-scale architecture that addresses memory bandwidth bottleneck for inference (key bottleneck for reasoning/agentic AI per the disclosed "frontier model" thesis). Cloud business is +93% YoY; hardware is +69%. OpenAI MRA validates the architecture at scale ($20B+ commitment). Take-or-pay structure on customer side means revenue commitments are durable (customer pays whether or not they use the capacity). G42 concentration is being diluted by additional customers (MBZUAI, OpenAI, AWS). Founder still CEO; multi-product platform articulated (chips + cloud + inference services). 9 years of operating history. Multi-class voting structure but no disclosed self-dealing (G42 equity attempt was blocked by CFIUS, so the major customer is NOT a shareholder — clean separation).

*Bear case at the time:* **Sovereign concentration is essentially 86% from UAE** (G42 + MBZUAI are both UAE entities; MBZUAI is the AI university affiliated with the Mohamed bin Zayed family). The "deconcentration" from G42 85% (2024) to G42 24% + MBZUAI 62% (2025) is a shift between UAE-affiliated counterparties, not a true broadening of customer base. Forward exposure shifts toward OpenAI: $20B MRA "represents a substantial portion of our projected revenues over the next several years." OpenAI MRA includes $1B working capital loan with covenants — if CBRS misses delivery milestones, OpenAI can effectively control disposition of those funds. Heavy customer financing of operations. Gross margin DECLINING (42.3% → 39.0%) driven by cloud capacity ramp eating margin (Cloud GM 61% → 30%). Take-or-pay creates revenue visibility AND delivery risk — failure to deliver capacity tranches gives OpenAI termination rights. WSE architecture isn't standards-based — high vendor lock-in risk to TSMC for advanced nodes; if TSMC capacity tightens, CBRS at the back of the line behind hyperscaler ASICs. Inference market evolving rapidly — Google TPU v6, Anthropic Trainium, AWS Inferentia all in production; CBRS's architectural advantage may not persist. Hardware revenue is from selling boxes — repeats only when customers expand. Hardware ≠ recurring revenue.

**Pre-profit-growth-framework gate-by-gate dry run.**

| Gate | Pass / Fail | Notes |
|---|---|---|
| Pre-check: TTM revenue ≥ $100M | ✓ | $510M FY2025 |
| Pre-check: Op income ≤ 0 | ✓ | -$145.9M operating loss |
| Pre-check: ≥1 audited fiscal year | ✓ | 2 years disclosed |
| Disqualifier: Sharp recent-year deterioration | ⚠ borderline | GM worsened 42.3% → 39.0% (-3.3pp); framework threshold is >5pp. Cloud GM specifically went 61% → 30% which is >30pp deterioration but blended is what counts. Borderline — does NOT trigger automatic disqualifier but is concerning. |
| Disqualifier: Self-dealing | ✗ none | G42 equity investment was BLOCKED by CFIUS; G42 is not a shareholder. Major customer is not an insider. Clean separation despite sovereign relationship. |
| Disqualifier: Self-disclosed structural unprofitability | ✗ none | Path to break-even articulated through scale + cloud growth |
| Disqualifier: Invented non-GAAP metric | ✗ none | Non-GAAP operating loss excludes SBC and revaluation — standard adjustments |
| **Cap structure: Software path (GM ≥70%)** | **✗ FAILS** | Blended GM 39%; even pure cloud is only 30% in 2025 (down from 61%) |
| **Cap structure: NWC path (GM ≥15%)** | **⚠ borderline pass** | GM ✓ (39%); capex/rev — not extracted; OCF -2% margin (close to break-even); repeat customer ≥40% — UNCERTAIN. The "repeat customer" framing doesn't fit cleanly: G42 is repeating but lower spend; new mega-customers (OpenAI, MBZUAI) dominate. Functionally, sovereign + new strategic = customer base concentrated in counterparties making large up-front commitments, not a true repeat-customer flywheel. |
| **Hard req: Customer concentration ≤10%** | **✗ CATASTROPHIC FAIL** | Top customer 62%; combined UAE sovereign concentration ~86% |
| **Hard req: Concentration trajectory** | **⚠ ambiguous** | G42 went 85% → 24% (looks deconcentrating) BUT MBZUAI replaced as 62% top customer. If you treat G42+MBZUAI as one UAE bloc: 85% → 86%. Functionally not deconcentrating. |
| Hard req: Operating history ≥3 years | ✓ | 9 years (founded 2016) |
| Hard req: Pre-IPO capital / TTM revenue ≤5x | ✓ | $1.72B / $510M = 3.4x |
| Hard req: Off-balance-sheet commitments ≤3x revenue | UNCERTAIN | Not extracted in spike; data center buildouts for cloud capacity likely create lease commitments |
| Hard req: NRR ≥120% (software path) | UNCERTAIN | Not disclosed; hardware doesn't have NRR; cloud is too new to have a meaningful 4-quarter NRR |
| Soft: Cash flow inflection (CFO+ within 24 months) | UNCERTAIN | OCF +$452M (2024 with prepayments) → -$10M (2025). Underlying trajectory hard to read through the prepayment lumpiness. |
| Soft: S&M efficiency ≥0.5x | ✓ strong | Revenue +$220M / S&M $70.6M = 3.1x |
| Soft: Multi-product expansion | ✓ | Chips + Cloud + Inference services + soon AWS marketplace distribution |
| Soft: Founder still at company | ⚠ qualified | Founder CEO ✓; **but multi-class super-voting structure with 99.2% voting power retained by existing holders**. Per framework: "Founder still + no super-voting + no self-dealing" required for the bullish version. CBRS has the founder but ALSO has super-voting → soft signal is **neutral, not positive**. |
| Soft: Operating margin trajectory improving 3+ consecutive years | UNCERTAIN | Only 2 years disclosed; -34.9% → -28.6% improving but framework requires 3 consecutive. |

**Verdict per framework: REJECT** on multiple gates:
- Hard requirement: customer concentration (catastrophic — top customer 62%, sovereign bloc ~86%)
- Hard requirement: concentration trajectory (ambiguous — apparent deconcentration is rotation within UAE bloc, not genuine broadening)
- Cap structure: Software path fails; NWC path borderline at best
- Multiple UNCERTAIN flags (NRR, OCF inflection, multi-year margin trajectory, off-balance-sheet commitments) → **per bias-to-rejection rule, UNCERTAIN resolves to reject**

**Acceptable false negative pattern check:** CBRS matches 4 of 4 markers in the framework's "NVDA/TWLO/ROKU acceptable false negative" cluster:
1. Founder-CEO ✓ (Andrew Feldman)
2. Super-voting structure ✓ (99.2% voting retained by existing holders)
3. Customer concentration failing literal gate ✓
4. Multi-product platform articulated ✓

Per the framework doc: "When 3+ of these signals are present, expect rejection AND expect the name might be a re-entry candidate after 1-2 years of structural risk dissipation (concentration normalizes, OCF stably positive, governance softens)."

This means CBRS is correctly classified by the framework as a reject-now-but-track candidate.

**Signal observations.**

| Signal | Discriminating? | Notes |
|---|---|---|
| Sovereign customer concentration | ✓ strong (semi-specific) | UAE umbrella covers G42 + MBZUAI (and likely future entities). Apparent deconcentration was a same-sovereign rotation, not genuine broadening. The framework's customer-look-through rule needs a "sovereign / common-control look-through" extension |
| Customer-funded operations (working capital loan) | ✓ moderate | $1B from OpenAI is structurally similar to PE-backed revenue commitments — comes with covenants and termination rights. Framework should flag customer-funded operations as a fragility signal even when it looks like cash flow strength |
| Take-or-pay on revenue side | ⚠ mixed | Positive: durable revenue visibility. Negative: delivery obligations create operational risk if execution slips. Net: less of an unalloyed positive than the bull case suggests |
| Cloud GM collapse (61% → 30%) | ✓ strong | The cloud segment was the cleanest "Software path" candidate; GM collapsed under capacity ramp. A SaaS company would have stable/growing GM at scale; CBRS cloud is structurally lower-margin because it's fronted by hardware capex |
| Hardware revenue ≠ recurring | ✓ moderate | Hardware revenue requires customer expansion, not subscription renewal. The framework's NRR / repeat-customer gates don't translate well |
| Wafer-scale architecture moat | ✓ moderate (qualitative) | Genuine architectural differentiation, but not standards-based. Lock-in risk both ways: customers locked to CBRS, CBRS locked to TSMC 5nm |
| Multi-class super-voting + founder | semi-specific quirk | Combined with no self-dealing (G42 equity was blocked by CFIUS), this is the cleanest version of the NVDA-cluster pattern. Framework correctly downgrades the soft signal to neutral, not positive |
| 9 years operating history with 3 product generations | ✓ moderate | More mature than typical pre-profit IPO; 3 generations validates engineering capability |
| Hardware revenue +69% / Cloud +93% | ✓ strong | Both segments accelerating, with cloud outpacing hardware — supports the "transition to cloud" narrative |

**Gate-calibration findings for the framework.**

1. **"Sovereign / common-control look-through"** for customer concentration — when multiple counterparties share a sovereign owner or political affiliation (G42 + MBZUAI = both UAE), they should be treated as a single concentration counterparty. Without this rule, the framework misreads CBRS as "deconcentrating" when the underlying exposure is unchanged.
2. **Customer-funded operations** (working capital loans, prepayments, take-or-pay deposits) need a separate gate. They look like cash flow strength but create covenant + delivery risk. Suggested gate: customer-funded cash / TTM revenue ≤30% (above this, classify as customer-financed and apply discount to the OCF signal).
3. **Cloud GM in hybrid hardware/cloud businesses** is the cleanest test of "is the cloud actually SaaS-grade economics?" CBRS cloud GM going 61% → 30% under capacity ramp shows it's not — it's hardware-fronted compute, not software. Framework should evaluate segment GM separately AND require that if cloud is positioned as the growth driver, cloud GM trajectory must be stable or improving (not collapsing during ramp).
4. **NVDA-cluster pattern check** is valuable — CBRS scores 4/4 markers cleanly. From this single observation, the pattern *appears* to be the dominant shape of AI infrastructure pre-profit IPOs (founder-CEO + super-voting + sovereign or strategic concentration + multi-product platform). Worth confirming as more AI systems IPOs surface; if it holds, the framework's existing language on this cluster should be expanded to make the re-entry-tracking action explicit, not just a footnote.

**Data quality.** Excellent on revenue mix, GM by segment, customer concentration (all explicitly disclosed in risk factors and MDA). Strong on related-party (the G42 CFIUS rejection is a clean disclosure that removes the self-dealing concern). Moderate on OCF (lumpy due to prepayments — would need underlying-cash analysis for clean signal). Weak on capex specifics (need to read cash-flow narrative). Sufficient for framework verdict.

**Outcome to date (live application — not yet IPO'd as of 2026-05-13).** Pricing terms not yet set; range $35-50 reportedly under discussion. **Framework verdict at this S-1: REJECT, with explicit "track for re-entry candidate after 1-2 years" note per the NVDA-cluster acceptable-false-negative pattern.** Re-evaluation triggers: (a) first 10-K post-IPO showing whether OpenAI revenue concentration becomes the new dominant exposure, (b) cloud GM trajectory (does it inflect back toward 50%+ or stay structurally below 35%), (c) whether AWS distribution materially diversifies the customer base, (d) whether CFO becomes consistently positive once prepayment cycle normalizes.

---

## Synthesis

**Cohort summary** (4 reviews complete):

| Name | Year | Sub-type | Framework verdict | Actual outcome |
|---|---|---|---|---|
| GFS | 2021 | Foundry | REJECT (3 gates: deterioration disqualifier + cap structure + concentration) | Mediocre — flat below IPO price 4.5 years on |
| GTAT | 2008 | Specialty equipment | OUT-OF-SCOPE (already GAAP-profitable); would REJECT on concentration gates if forced | Bankruptcy 2014; -95% from IPO |
| ALAB | 2024 | Fabless specialty | REJECT (10% concentration) — but matches "deconcentrating + durable end-customer" pattern | Strong success-in-progress; up significantly from IPO |
| CBRS | 2026 | AI systems | REJECT (sovereign concentration + cap structure + uncertain flags) — matches NVDA-cluster acceptable-false-negative | Live; not yet IPO'd |

### Did the existing framework correctly classify each name?

**Yes, in 3 of 4 cases.** GFS and GTAT failures are correctly anticipated by the gates (GFS by the deterioration disqualifier; GTAT by the concentration gate, with pre-check correctly routing it to a different framework). CBRS is correctly classified as the NVDA-cluster reject-now-but-track pattern.

**Concerning: ALAB.** A clear success post-IPO is rejected by the literal framework on the customer concentration gate. ALAB scored well on every other dimension (GM 69-74%, capex/rev <5%, OCF improving 30+pp, deconcentrating fast, design-win breadth) but the 10% concentration rule alone produces a reject. This is the strongest evidence that the gate needs sector-specific recalibration.

### Which gates needed semi-specific recalibration?

1. **Customer concentration (10% rule)** — Both ALAB (success-in-progress) and GTAT (failure) trip this gate badly. The discriminating variables are concentration *trajectory*, end-customer durability, and gross margin — not the level. **Suggested recalibration**: for semis, raise the static threshold to 25-30% AND apply a "sovereign / common-control look-through" rule (treat counterparties under common ownership as one). When the concentration *trajectory* is improving and the end customers are creditworthy (hyperscalers, sovereigns with delivery commitments), apply a 50% weight to the concentration signal rather than treating it as a hard fail.

2. **Cap structure paths** — Pure Software path (GM ≥70%) is rare for semis even at maturity. ALAB at 69-74% is the closest fit; CBRS at 39% blended fails it; GFS at negative GM fails it; GTAT at ~30% fails it. The NWC path (GM ≥15%, repeat customer ≥40%) doesn't fit either because semis don't have repeat customers in the SaaS sense — they have take-or-pay LTAs (foundries), design wins (fabless), or sovereign capacity commitments (AI systems). **Suggested addition**: a third "Semi" path with sub-paths for foundry / fabless designer / AI systems with sub-type-specific gates.

3. **R&D intensity should be evaluated as a trajectory** — ALAB at 92% looks scary, 63% is high but normal for hardware, and probably 35-40% at maturity. CBRS at 48% is similar pattern. GFS *cutting* R&D from 15% to 10% is a structural warning even though the absolute level is "fine." **Suggested recalibration**: for semis, R&D trajectory matters more than level. Cutting R&D = warning regardless of where you started.

4. **OCF trajectory over level** — ALAB at -11% with +34pp YoY improvement is a much stronger signal than CBRS at "+$452M" the bulk of which is customer prepayments under take-or-pay contracts. **Suggested recalibration**: for semis with material customer prepayments / take-or-pay deposits, separate "underlying OCF" from "OCF including customer-funded working capital" before applying the cap-structure gate.

5. **Multi-class voting + founder** — CBRS has the founder-CEO + super-voting combination that the framework correctly downgrades from "bullish" to "neutral." This is the right call. The framework's existing language is correct.

### What new gates surfaced that should be added?

1. **Sovereign / common-control look-through** for customer concentration (CBRS exposed this gap)
2. **Customer-funded operations gate** — when customer prepayments + working capital loans + take-or-pay deposits exceed 30% of TTM revenue, classify as customer-financed and apply downside-risk discount (CBRS exposed this; GTAT had similar pattern with order-backlog-as-revenue-proxy)
3. **End-market subsidy dependency** — when >30% of end-customer demand is policy-driven (solar credits, EV credits, CHIPS Act, sovereign AI initiatives), apply downside-risk discount (GTAT canonical; potentially affects CBRS via UAE sovereign AI; affects RIVN/LCID via EV credits)
4. **Sub-type classification** — semis split into foundry / specialty equipment / fabless designer / AI systems, each with different normal ranges for GM, R&D intensity, customer concentration, and capex

### Conclusion: extend the existing framework or build a separate one?

**Recommendation: extend, don't replace.** The existing pre-profit-growth-framework gate structure (pre-check → disqualifiers → cap structure → hard requirements → soft signals → verdict) is sound. The semi cohort exposed gate calibration issues, not structural framework issues. Suggested specific changes:

1. Add a **Semi sub-path** to the cap-structure prerequisite (alongside Software and NWC paths), with sub-type-specific gates
2. Add **3 new hard requirements** for semis: sovereign/common-control look-through on concentration; customer-funded-operations cap; end-market subsidy dependency cap
3. **Recalibrate the customer concentration threshold** for semis from 10% to 25-30%, with weighted credit for trajectory + end-customer durability
4. **Document explicitly** that for AI infrastructure pre-profit IPOs, the NVDA-cluster acceptable-false-negative pattern is the modal case, not the exception — and that re-entry tracking is the practical action item, not just a framework note

### Cohort study limitations

- **N=4** is small. Findings are directional, not statistically robust.
- **No truly successful asset-heavy semi IPO** in the cohort — TSM 1997 used F-6 ADR registration (not F-1, so no prospectus to extract); INTC 1971, AMD 1972, and AMAT 1972 all predate the EDGAR mandate. The "winner pattern" is inferred from contrast with failures, not directly observed.
- **CBRS outcome is unknown** — it's a live application, not a backtested name. The framework's "reject but track" call is testable only post-IPO.
- **ALAB outcome is partial** — 14 months post-IPO is not enough to validate "winner" status; needs another 2-3 years.

**Confidence level on the recalibrations:** Medium. The customer-concentration recalibration is well-supported (clear contrast between ALAB and GTAT on trajectory + end-customer durability). The Semi sub-path proposal is more speculative — would benefit from another 4-8 names before formalizing.

### Suggested next steps

1. **Apply the recalibrated framework to CBRS at IPO** as the live test case. Document whether the recalibration changes the verdict (it might not — CBRS still fails on multiple gates even with relaxed concentration threshold).
2. **Add 4-6 more semi names** to deepen the cohort: MU 1984 (memory cycle survivor), Nikola 2020 (SPAC failure), Lucid 2021 (SPAC mediocre), Wolfspeed (SiC pivot post-2021), QuantumScape (battery materials, similar profile), Indie Semi (auto semi recent IPO). Most are post-EDGAR so should be extractable. Pre-1996 names (AMD 1972, INTC 1971, AMAT 1972) remain out of reach.
3. **Update `pre-profit-growth-framework.md`** with the Semi sub-path and 3 new hard requirements once cohort expands to N≥8.
4. **Track ALAB and CBRS** at each post-IPO 10-K to validate or invalidate the framework's verdicts. Both are explicit re-entry candidates.
