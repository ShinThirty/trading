---
description: Evaluate the structural tail-risk hedge program (Universa-style)
---

Manage the structural tail-risk hedge program per [tail-hedge-playbook.md](../../docs/tail-hedge-playbook.md). Evaluate whether one of the playbook's three triggers has fired and surface the action. **Never open, close, or resize on cleared signals** — the playbook holds the rationale; this skill is the operational loop.

The program: **deep OTM (20-25%) SPY puts, 90-120 DTE, rolled on discipline, never closed because nothing is wrong.** Correction-zone protection (5-15% OTM) is off-limits (playbook Mistake 2) — for that, trim, hold cash, or use single-name puts.

## Step 1: Inventory the hedge

In parallel:
- `get_account_positions` for the margin account `7PGI7F1AV89E2FBFTK4HDK1JIB` (where the program lives)
- `decision_list` source `hedge` for entry/anchor context
- `get_portfolio_summary` for live put P&L %

Classify each open SPY/QQQ put by strike depth from spot:

| Depth | Classification | Action |
|---|---|---|
| 20-30% OTM | Sweet spot | Evaluate per Step 3 |
| 15-20% OTM | Edge of tail | Step 3; consider deeper at next roll |
| <15% OTM | Shallow (legacy correction-zone) | Roll to 25% OTM at next window |
| >30% OTM | Drifted out (rally) | If DTE > 45-50, roll up to 25% OTM (Trigger 1 rally side) |

No hedge on the books → skip to Step 5 (the commit/skip question, governed by [When to deploy](../../docs/tail-hedge-playbook.md#when-to-deploy), not signals).

## Step 2: Pull trigger inputs

In parallel: `get_quote SPY,VIX,VIX3M` · `get_tradier_history VIX` and `SPY` (60+d) · `get_quote` each put with `greeks=True` · `get_market_regime` (**informational only** — never drives hedge actions).

Compute:

| Input | Source | Used by |
|---|---|---|
| Put delta | `get_quote greeks=True` | T1 drop |
| Strike depth (% OTM) | (spot − strike) / spot | T1 rally |
| Rally from strike anchor | current SPY vs entry/last-roll SPY (`decision_list`) | T1 rally |
| VIX retracement from spike high | VIX history | T1 |
| Put P&L % | `get_portfolio_summary` | T1 + T2 |
| SPY drawdown from recent high | SPY history | T2 |
| DTE remaining | put expiry | T3 (window 45→30) |
| Today's tape color + VIX vs 60d range | `get_quote SPY` day change % + VIX history | T3 (green / low-vol roll timing) |

## Step 3: Evaluate the triggers

Priority order, first match wins. None fire → **hold**.

### Trigger 1: Maintenance roll (bidirectional drift)

Put drifted out of the 20-30% sweet spot; restore the 25% profile from current SPY. Check both directions.

**Drop side (roll down)** — both of:
- Put delta **-0.20 to -0.40** (was ~-0.05 at entry), AND
- one of: VIX retraced ≥50% from spike high / catalyst resolved / P&L 100-300% and stalling.
- Skip if: delta tighter than -0.15, VIX still climbing or >30, SPY making new lows daily (T2 may be coming), or P&L only 50-100%.

**Rally side (roll up)** — all three:
- Strike depth **>~30% OTM** (primary trigger — % OTM, not delta), AND
- **DTE > 45-50**, AND
- SPY **≥~10%** above the strike anchor.
- Skip if: routine roll is near, rally <10%, or IV Rank >50%. Rally side *costs* premium (drop side harvests) → higher bar; it's an exception handler for fast melt-ups, not routine.

### Trigger 2: Harvest tranches (real crash)

Large AND fast — VIX >50, SPY down 20%+, puts deep ITM. Mechanical, don't top-tick. Read live P&L % from `get_portfolio_summary`.

| P&L | Action |
|---|---|
| +400% (5x) | Close 50% |
| +900% (10x) | Close another 25% of original |
| +1900% (20x)+ | Close remainder (residue rides only if grinding lower with fresh legs) |

### Trigger 3: Routine calendar roll (window, not a date)

Window opens ~45 DTE, hard backstop at 30 DTE:

- **DTE > 45** → not open; hold (unless T1/T2).
- **45 ≥ DTE > 30** → roll on the **first green / low-VIX day** (SPY green AND VIX in the lower half of its 60d range = cheaper replacement put). Else **armed-and-waiting HOLD** — surface "window open, waiting for green; backstop <date at 30 DTE>."
- **DTE ≤ 30** → **hard roll regardless of color.** Continuity beats a cheaper entry.

Green is a preference inside the window, never a reason to breach the 30-DTE floor.

### Universal close+redeploy workflow (any trigger)

Sell the tranche (full for T1/T3, partial for T2) → `calculate_hedge` (current SPY, `crisis_multiplier=1.25`, `fidelity_folder`) → buy new at 25% OTM from *current* SPY → `decision_close` (old) + `decision_add` `WRITE_NEW` source `hedge` (new).

## Step 4: Cost tracking

`get_order_history` for the margin account `7PGI7F1AV89E2FBFTK4HDK1JIB`, filter SPY/QQQ puts.

| Metric | Target | If breached |
|---|---|---|
| Annual drag % | 0.5-1.5% | Above 2%: strike too shallow (correction-zone in disguise) or entering at IV Rank >50% |
| Hedges closed / P&L YTD | tracking only | Negative P&L is the modal outcome |

**Don't** apply "3+ rolls without payoff = reduce." The playbook expects 3-7 consecutive losing years — that's the design.

## Step 5: Recommendation

### If a hedge exists

**Action: [HOLD / ROLL WINDOW OPEN — WAITING FOR GREEN / MAINTENANCE ROLL DOWN / MAINTENANCE ROLL UP / HARVEST TRANCHE / CALENDAR ROLL]**

| Field | Value |
|---|---|
| Position | N contracts, K strike, exp |
| Strike depth | X% OTM (sweet spot / edge / shallow / drifted-out) |
| Put delta | -X.XX |
| Rally from anchor | +X.X% |
| DTE | X |
| Put P&L % | X% |
| VIX vs recent high | X.X / Y.Y (Z% retrace) |
| SPY drawdown | -X.X% |
| Trigger | None / T1 down / T1 up / T2 [%] / T3 (window — waiting) / T3 (backstop) |
| Annual drag YTD | X% (vs 0.5-1.5%) |

**Rationale:** one sentence, anchored on trigger criteria — not signals or feel.

Non-HOLD → `preview_order` first, then place; record `decision_close` + `decision_add` (source `hedge`).

### If no hedge exists

A one-time commitment question, not a signal entry. Surface [When to deploy](../../docs/tail-hedge-playbook.md#when-to-deploy) inputs: net delta (`get_portfolio_greeks`), equity % (`get_portfolio_summary`), trailing beta (`calculate_hedge`), cash buffer. Defer to the playbook. If committing: size via [Sizing](../../docs/tail-hedge-playbook.md#sizing), follow the [Execution checklist](../../docs/tail-hedge-playbook.md#execution-checklist), record `decision_add` (source `hedge`).

## This skill does NOT

- Open/close on signals (regime, vol, divergences) — those drive sizing/pipeline
- Recommend correction-zone (5-15% OTM) puts — trim or cash instead
- Close on cleared signals or premium decay — only the three triggers
- Time entry on IV, beyond skipping strikes at IV Rank >50%

Single-stock catalyst hedges → long puts per [strategy-catalog.md](../../docs/strategy-catalog.md), not this skill.
