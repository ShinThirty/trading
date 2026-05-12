---
description: Run the pre-profit speculative-growth framework against an upcoming or recent IPO
arguments:
  - name: symbol
    description: Ticker assigned in the S-1. Pre-IPO names need an assigned ticker — if unassigned, run /sec instead and pass the accession directly.
    required: true
---

Run the **pre-profit speculative-growth framework** ([docs/pre-profit-growth-framework.md](docs/pre-profit-growth-framework.md)) against **$ARGUMENTS.symbol**'s S-1 / F-1 / 424B prospectus. Walk every gate in order. The framework is bias-to-rejection by design — borderline cases default to reject.

**Important:** This is a *mechanical* framework run, not narrative analysis. Cite the specific gate that drives each verdict. For cohort examples and detailed rationale per gate, defer to the framework doc — don't restate them here.

---

## Phase 1: Locate the filing

Call `get_ipo_s1 symbol=$ARGUMENTS.symbol`.

Capture the chosen accession + primary document. If the response is an error (no S-1 found, ticker not in EDGAR map), halt with: "⚠ No S-1-family filing for $ARGUMENTS.symbol — verify ticker is assigned, or check for F-1 (foreign issuer) under a different ticker."

If multiple amendments exist, note this — final 424B has the priced terms; S-1/A amendments have updated disclosures but no final pricing. The chosen filing is what we'll analyze.

---

## Phase 2: Pre-check (must all pass to be in scope)

Fetch the financial spine in parallel — single message, two tool calls:

- `get_ipo_section symbol=$ARGUMENTS.symbol accession_number=<accession> document=<doc> section=mda`
- `get_ipo_section symbol=$ARGUMENTS.symbol accession_number=<accession> document=<doc> section=summary_financial_data`

From these, extract:

| Pre-check gate | Pass condition |
|---|---|
| **TTM revenue ≥ $100M** | Below this is venture-stage |
| **Op income ≤ 0** (not yet GAAP-profitable) | If already profitable, this framework doesn't apply — route to a different intent tier |
| **≥ 1 audited fiscal year disclosed** | Less than this and there's no basis to evaluate |

If any pre-check fails, **halt with**: "**OUT-OF-SCOPE.** [Specific gate that failed]. Use [different framework] instead." Do not proceed.

If all pass, state the pre-check numbers explicitly and continue.

---

## Phase 3: Disqualifying signals (any one = automatic REJECT)

Fetch in parallel:

- `get_ipo_section ... section=risk_factors`
- `get_ipo_section ... section=related_party`

Then check **all four** disqualifiers — any single hit halts with REJECT verdict:

| Disqualifier | Evidence to look for | Source section |
|---|---|---|
| **Invented non-GAAP metric** that excludes basic operating costs | Custom adjusted-EBITDA-style metric whose adjustments aren't standard (excluding G&A, S&M, etc.) | mda |
| **Self-dealing transactions** between founder/insiders and the company | Founder lease, IP sale to founder, related-party loan with non-arm's-length terms | related_party |
| **Sharp deterioration in most recent year** | OCF flipping negative YoY, op margin worsening >5pp YoY, GM worsening >5pp YoY | mda |
| **Self-disclosed structural unprofitability** | Honest statement of "expect losses to continue for N+ years and increasing" or equivalent | risk_factors |

If any disqualifier is hit, **halt with**: "**REJECT** — Disqualifying signal: [name]. Evidence: [quote 1-2 sentences from the filing]." Do not proceed.

If all four are clean, state "Disqualifiers: ✓ none triggered" and continue.

---

## Phase 4: Capital structure prerequisite (one of two paths must pass)

Using the MDA + summary_financial_data already fetched, extract:

- Gross margin (most recent fiscal year)
- Capex / revenue (most recent fiscal year, look in cash flow narrative)
- Operating cash flow (CFO) margin
- For software: NRR / Net Revenue Expansion if disclosed
- For NWC: Repeat customer rate or NRR equivalent

Test BOTH paths:

| Path | Required |
|---|---|
| **Software path** | GM ≥ 70%, Capex/rev ≤ 10%, CFO margin positive OR clearly improving toward positive |
| **NWC path** | GM ≥ 15%, Capex/rev ≤ 10%, CFO margin positive (or break-even), Repeat customer rate ≥ 40% disclosed |

**Always evaluate consolidated economics, not segment economics.** A clean SaaS-like segment can mask a capex-heavy consolidated business — subscription metrics in isolation can mislead.

If neither path passes → **halt with REJECT**: "**REJECT** — Cap structure prerequisite. Software path fails on [GM/capex/OCF]. NWC path fails on [GM/capex/OCF/repeat]. Asset-heavy businesses (hardware, CPG, biotech, manufacturing) typically fail both."

If at least one passes, state which (or both) and continue. Note any UNCERTAIN extractions (e.g., NRR not explicitly disclosed).

---

## Phase 5: Hard requirements (all must pass)

Fetch in parallel — single message, multiple tool calls:

- `get_ipo_concentration symbol=$ARGUMENTS.symbol accession_number=<accession> document=<doc>`
- `get_ipo_section ... section=capitalization`
- `get_ipo_section ... section=use_of_proceeds`
- `get_ipo_section ... section=business`

Test all 7 hard requirements:

| Hard req | Pass condition | Source |
|---|---|---|
| **Customer concentration** | No counterparty >10% of revenue. Look-through to whoever physically pays (distributors count if they're the legal counterparty) | concentration tool |
| **Concentration trajectory** | Stable or decreasing. A single customer % *increasing* over disclosed periods is **more dangerous** than a static 10%+ | concentration tool |
| **Operating history** | ≥ 3 years pre-public-disclosure. Allow 2+ years only with hyper-acceleration evidence | summary_financial_data + mda |
| **Pre-IPO capital raised / TTM revenue ≤ 5x** | Winners cluster 0.2–2.7x; failures sit much higher | capitalization + summary_financial_data |
| **Off-balance-sheet commitments ≤ 3x revenue** | Future minimum lease + inventory + capex commitments / TTM revenue | mda (contractual obligations) + risk_factors |
| **No asset-liability duration mismatch** | Revenue duration must match liability duration (long-dated leases against short-dated revenue = built-in fragility) | business + risk_factors (qualitative) |
| **Path-specific:** For software → NRR ≥ 120% for 4+ consecutive quarters. For NWC → Repeat customer rate ≥ 40% AND increasing or stable | — | mda + business |

**For each hard req, present:** ✓ pass / ✗ fail / ⚠ UNCERTAIN. Include the specific number cited from the filing.

If any hard req fails → **halt with REJECT**: "**REJECT** — Hard requirement: [gate name]. Specifically: [number from filing] vs threshold [X]." Reference the cohort table in the framework doc for the closest historical match.

**Bias-to-rejection enforcement:** If a metric is not extractable from the filing prose (e.g., NRR not explicitly disclosed), mark it **UNCERTAIN** — do not silently default to pass. Track all UNCERTAIN flags for the verdict.

If all 7 pass cleanly, state "Hard reqs: ✓ 7/7" and continue.

---

## Phase 6: Soft signals (need 3+ of 5)

Fetch the remaining sections needed for soft-signal scoring:

- `get_ipo_section ... section=management`
- `get_ipo_section ... section=principal_stockholders`

Score the 5 soft signals — bullish if condition is met:

| Signal | Bullish if... | Source |
|---|---|---|
| **Cash flow inflection** | CFO+ at S-1 OR clear path to CFO+ within 24 months | mda |
| **S&M efficiency** | $ revenue growth / $ S&M spend ≥ 0.5x | mda |
| **Multi-product expansion** | No single product >50% of revenue OR clear multi-product roadmap articulated | business |
| **Founder still at company** | CEO or CTO is founder, **AND no super-voting structure abuse, AND no disclosed self-dealing**. Multi-class structure alone is neutral, not negative | management + principal_stockholders + related_party |
| **Operating margin trajectory** | Improving for 3+ consecutive years, NOT a one-year breakout. Single-year peaks are misleading | mda + summary_financial_data |

For each, present: ✓ pass / ✗ fail / ⚠ uncertain.

If <3 of 5 pass → **REJECT** with: "**REJECT** — Soft signals: only [N]/5 passed. Below the 3/5 threshold."

If 3+ pass cleanly, continue to verdict.

---

## Phase 7: Verdict + sizing guidance

Synthesize the verdict in this exact format:

```
**VERDICT: [CLEAR PASS | BORDERLINE PASS | REJECT | OUT-OF-SCOPE]**

Pre-check:        [✓ all 3 / ✗ failed: <gate>]
Disqualifiers:    [✓ none / ✗ <name> + evidence quote]
Cap structure:    [Software / NWC / both / neither]  <key metrics>
Hard reqs:        [N/7 pass]  <which failed + specific number vs threshold>
Soft signals:     [N/5 pass]  <which passed>
UNCERTAIN flags:  [count + list]

Closest cohort match: <reference the framework doc's cohort table — name the historical pattern, not the inline ticker>

Strategy if pass:
  - Position size cap: 3% (borderline-pass) or 5% (clear-pass) of portfolio
  - Initial deployment: single tranche; no scale-in until first post-IPO 10-K validates
  - Strategy: direct buy preferred (CSP collateral inefficient when stock is volatile)
  - Long calls only if IV Rank <40 (most pre-profit IPOs have rich IV)
  - No spreads / no leverage until business proves out (multiple consecutive years of CFO+)

Re-evaluation trigger: <next 10-K release date> or <specific disclosure: major customer loss, restructuring, etc.>
```

**Bias-to-rejection enforcement (final check):**
- If verdict landed at BORDERLINE PASS AND any UNCERTAIN flag is open → **downgrade to REJECT** with note: "Per `feedback_speculative_growth_bias.md`, uncertainty resolves to reject. Re-evaluate at next 10-K when uncertain metrics become disclosed."
- If verdict landed at REJECT on a single specific gate (concentration, OCF inflection) AND the name otherwise matches the "acceptable false negative" cluster pattern (founder + super-voting + concentration + multi-product platform articulated), per the framework doc → note: "Reject is correct per framework discipline. Track for re-entry candidate after 1-2 years of structural risk dissipation."

**Don't credit hypothetical pivots.** Evaluate the IPO-era business as it is, not for what it might become (per `feedback_pivot_optionality.md`).

---

## Notes

- Run all sections in Phase 5 as **parallel** tool calls (single message, multiple tool uses). Do not serialize.
- The concentration tool searches MDA + Risk Factors + Business automatically — don't also grep these sections by hand for concentration disclosures.
- For tabular concentration disclosures ("Customers that each accounted for 10% or more..."), the actual table sits in the F-pages (Notes to Financials), not in the extracted sections. The concentration tool flags this — if you see a `table_intro` hit, fall back to `get_filing_content symbol=$ARGUMENTS.symbol accession_number=<accession> document=<doc> offset=...` to read the F-pages.
- F-1 filings (foreign issuers) are in scope — same framework, same tool calls.
- Skip this skill for already-public names — use `/analyze` instead.
