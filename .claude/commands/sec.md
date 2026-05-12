---
description: Read SEC filings — pipeline sweep, single-ticker deep read, or targeted accession read
arguments:
  - name: symbol
    description: Ticker (e.g. NVDA). Omit for pipeline-wide sweep.
    required: false
  - name: accession
    description: Filing accession number (e.g. 0000320193-26-000011) for targeted read.
    required: false
---

Dispatch by argument shape:

- **No args** → run **Mode A: Pipeline Sweep** below.
- **`symbol` only** → run **Mode B: Deep Read** for `$ARGUMENTS.symbol`.
- **`symbol` + `accession`** → run **Mode C: Targeted Read** for `$ARGUMENTS.symbol` + `$ARGUMENTS.accession`.

In every mode, defer to `get_earnings_release` (already in the toolset) for any 8-K Item 2.02 — do NOT re-fetch the press release via `get_8k_exhibit`.

---

## Mode A: Pipeline Sweep

Use case: biweekly review punch list — what materially happened across the pipeline since the last sweep.

1. Call `scan_pipeline_filings days=14 min_tier=CAPITAL`.

2. Present the returned table verbatim. Then add a one-line verdict per ticker:
   - **MATERIAL 8-K**: "Read with `/sec $TICKER $ACCESSION` — likely thesis-shifting"
   - **EARNINGS** (10-Q/10-K or Item 2.02): "Run `/analyze $TICKER` if not already done post-print"
   - **CAPITAL** (S-1/S-3/424B): "Equity raise / shelf — check dilution math against thesis"
   - **INSIDER** (Form 4 cluster): "Surface via existing `insider_buying` watcher; only investigate if cluster size unusual"

3. If the Skipped section has entries, briefly note which tickers couldn't be looked up (foreign issuers, ETFs, recent IPOs) and move on — do not fail the sweep.

If the sweep returns no hits, say "✅ Pipeline quiet — nothing at or above CAPITAL tier in the last 14 days." That's a valid outcome.

---

## Mode B: Deep Read for $ARGUMENTS.symbol

Use case: thesis re-evaluation triggered by a recent print, drawdown, or pipeline review surfacing the name.

### Step 1: Scope the filings

1. Call `get_recent_filings symbol=$ARGUMENTS.symbol days=90`.

2. From the result, identify:
   - The **latest 10-Q or 10-K** (whichever is more recent — this is your periodic-filing target)
   - All MATERIAL-tier 8-Ks in the window
   - Whether the EARNINGS-tier rows include a recent 10-Q/10-K (vs just an Item 2.02 8-K)

If no 10-Q or 10-K within 90 days, note that and proceed only with 8-K analysis.

### Step 2: Periodic-filing read

For the latest 10-Q or 10-K, call **all four** of these in parallel (single message, four tool calls):

- `get_filing_section symbol=$ARGUMENTS.symbol accession_number=<accession> document=<primary_doc> section=mda`
- `get_filing_section symbol=$ARGUMENTS.symbol accession_number=<accession> document=<primary_doc> section=segments`
- `get_filing_section symbol=$ARGUMENTS.symbol accession_number=<accession> document=<primary_doc> section=cash_flow`
- For 10-K only, also: `get_filing_section ... section=risk_factors`

Then for each section returned, surface the **thesis-relevant texture only** — not the whole section. Specifically:

- **MD&A**: revenue/margin commentary, guidance language changes, segment-mix shifts, any "we expect / we anticipate" forward language. Skip the boilerplate "results of operations" recitation.
- **Segments**: extract the segment table. Flag concentration shifts (e.g., a single segment growing > 50% YoY while another contracts).
- **Cash flow**: capex, share buyback, dividend, debt issuance / repayment, deferred revenue. Anything that materially changes the FCF picture.
- **Risk factors** (10-K only): list the section's headline categories. Do NOT dump full text. If the user wants the diff vs prior 10-K, ask: *"Want me to run `diff_risk_factors` for $ARGUMENTS.symbol? It compares Item 1A vs the prior-year 10-K and surfaces only the deltas — useful but expensive (two large fetches)."*

If a section returns "Section not found in [doc]", note it and move on — issuer formatting variation is expected for some names.

### Step 3: Material 8-K read

For each MATERIAL-tier 8-K from Step 1:

- **Item 2.02 (Results of Operations)** → defer to `get_earnings_release symbol=$ARGUMENTS.symbol` (a separate tool that auto-discovers the latest one). Don't refetch.
- **Any other MATERIAL item** (1.01, 2.05, 4.02, 5.02, 7.01, 8.01) → call `get_8k_exhibit symbol=$ARGUMENTS.symbol accession_number=<accession>`.

Surface what changed:
- 1.01 / 1.02: deal terms (counterparty, value, conditions, termination triggers)
- 5.02: who left/arrived, severance terms, succession plan
- 4.02: which periods restated, why, magnitude
- 7.01 / 8.01: specifics of the disclosure

### Step 4: Synthesis

End with a 3-line verdict:

- **What changed** — the one or two facts from the periodic + 8-Ks that materially update the thesis
- **Conviction direction** — improving / deteriorating / unchanged, with the specific factor(s) driving it
- **Action** — pull a fresh `/analyze $ARGUMENTS.symbol`, hold, exit, or "no action — texture only"

---

## Mode C: Targeted Read for $ARGUMENTS.symbol $ARGUMENTS.accession

Use case: you already know which filing matters (saw it in news, or `scan_pipeline_filings` flagged it) and want the substance, not the index.

### Step 1: Identify form type

Call `get_recent_filings symbol=$ARGUMENTS.symbol days=365` and find the row matching `$ARGUMENTS.accession`. Note:
- Form (8-K / 10-Q / 10-K / 13D / S-3 / etc.)
- Items list (for 8-K)
- Primary document filename

If the accession isn't in the last 365 days, increase to `days=1825` (5y); if still missing, return: "⚠ Accession $ARGUMENTS.accession not found in $ARGUMENTS.symbol's last 5 years of filings. Verify the number against EDGAR."

### Step 2: Form-specific extraction

- **10-Q or 10-K** → run all four sections per Mode B Step 2 (parallel calls). Apply Mode B Step 2 surfacing rules.
- **8-K with Item 2.02** → defer to `get_earnings_release` (it auto-picks the latest, which is usually what you wanted anyway).
- **Any other 8-K** → `get_8k_exhibit`.
- **13D / 13D/A** → `get_filing_content` on the primary doc. Surface: filer, ownership %, purpose section, any board/strategy demands.
- **S-3 / 424B** → `get_filing_content` on the primary doc. Surface: shelf size, offering type, use of proceeds, dilution math.
- **Form 4** → call `get_filing_content`, parse the role + transaction codes (P=open-market purchase, S=sale). For richer context, the existing `insider_buying` watcher already handles cluster detection.
- **Anything else** → `get_filing_content` raw, with offset=20000 to skip XBRL preamble.

### Step 3: One-paragraph verdict

Same format as Mode B Step 4 — three lines: what changed, conviction direction, action.

---

## Notes

- All four `get_filing_section` calls in Mode B Step 2 are independent — issue them as parallel tool calls in a single message, not sequentially.
- `diff_risk_factors` is gated behind explicit user confirmation because it triggers two ~1MB filing fetches. The default deep read does NOT call it automatically.
- Risk factors only meaningfully change in the annual 10-K. Don't bother running `diff_risk_factors` against a 10-Q.
- Issuer formatting varies: a "Section not found" return from `get_filing_section` is expected for ~10% of filings (especially older or foreign-issuer formats). Fall back to `get_filing_content` for hand navigation.
