# AI-Capex Cycle Health Check & Watch-Only Governance

**Rewritten 2026-07-17.** This doc used to be a covered-call defense manual — "detect the capex turn early so you can tighten CC strikes before the gap-down." That framing is obsolete: the book exited the AI-capex theme on 2026-07-17 (see memory `project_ai_capex_theme_exit`), the cohort is now ~10% of NLV with the book ~81% cash, and 19 names sit in a **watch-only** tier. This doc's job now is **governance**: it decides, on objective signals, when each parked name should **re-enter** (relax to CSP-entry), **stay parked**, or **harden to short** (L2 long puts — the alarm-window trade).

**Run the baseline check monthly (10th–15th).** Run the event-driven checks when they trigger (earnings cluster, an AI mega-IPO print, an HY-OAS move, a neocloud-cohort crack). Cross-reference the daily reads already wired into `/briefing`: neocloud epicenter (1h), DRAM spot (1g), bear-regime score (1f).

---

## The core tension (why this is hard right now)

**The physical cycle is still accelerating while price, narrative, and macro have turned.** As of the 2026-07-17 exit:

- **Fundamentals — accelerating.** TSMC June 2026 revenue printed **+67.9% YoY, +6.2% MoM** — the strongest YoY in the trailing year. The foundry under every accelerator is not rolling over; it's speeding up. HBM, WFE guidance, and ODM sales were not confirming a turn either.
- **Price — diverging.** SMH −10.6% vs SPY (20d). The stocks are derating while the fundamentals accelerate — a classic late-cycle *price-leads-fundamentals* fingerprint (2000: capex peaked **after** the equities did; Cisco's best quarters were its last).
- **Narrative + macro — bearish.** Model-layer commoditization (China frontier models), circular capex financing, mega-IPO distribution, Bear-Setup regime, ERP Tight, Bear Steepener.

**So the exit deliberately front-runs the hard data.** That is a legitimate bet — the original thesis was "you cannot wait for the official announcement; by the time a CEO says 'capex moderation,' AVGO and VRT are down 20% after-hours." But it means the re-entry / harden-to-short decision must be **signal-gated**, not narrative-gated. The signal classes below tell you whether the hard data is *catching down* to the price (harden) or the price was *wrong* and fundamentals hold (re-enter). Two of these signal classes did not exist in the old doc and are exactly what drove the exit — **model-layer commoditization** and **capex funding stress**.

---

## The watch-list, tiered by unwind phase

The cycle frays from the edges inward, not all at once (see the four-phase unwind in Signal F). The tier sets each name's default governance. Higher tier = structurally later to roll = longer leash.

### Tier 0 — Exiting (sell now, then watch-only)
**QCOM, RMBS** (also CRM, no pipeline entry). Held positions being sold into the exit. All in Fidelity accounts (SnapTrade read-only) → manual sells. Zero tax friction (tax-advantaged wrappers).

### Tier 1 — Hard cut (froth; rolls first)
**CRDO, FN, AMD, MRVL, CLS, DOCN, PLTR.** High-multiple, customer-concentrated, pure GPU/optical-attach, or application-layer narrative names — the weakest hands, punished first (Phase 2). Governance: **no re-entry** without a genuine valuation reset *and* confirmed intact fundamentals. These are the **first to harden-to-short** (Tier-1 long puts) if funding stress (Signal E) fires — they have the least floor. Examples of what puts them here: CRDO P/E ~758 + top-2 customer 61%; FN single-customer optical attach + Liq 1; AMD PEG 3.73 / P/E 128; MRVL beta 2.15 + "next Nvidia" euphoria; CLS margin-compressing ODM; DOCN ROE −20% / D/E 31 / already −35% drawdown; PLTR most valuation-extreme application-layer.

### Tier 2 — Mid leash (core quality, cyclical)
**NVDA, MU, AVGO, LRCX, ADI.** Highest-quality pure-plays — monopoly/oligopoly, best PEGs, real cash flow — but still cyclical and still capex-derived. NVDA/MU are Phase-3 "last safe havens" (roll when the last man stumbles). AVGO decouples from NVDA on custom silicon (see nuance below) but carries the circular-financing red flag (XPU/Apollo vendor-financing Anthropic/OpenAI). Governance: **re-enter only** on the post-earnings-cluster reaction **and** a real pullback (not at ATH), per the physical signals still confirming. MU additionally governed by its own exit ladder (`~/Documents/analysis/MU/`) and the `/briefing` DRAM-spot check.

### Tier 3 — Longest leash (power/grid + hyperscaler hybrids; roll last)
**GEV, CEG, VRT, META, MSFT.** Power/grid names fray **last** — the physical grid bottleneck keeps their backlog full past the silicon cycle, and TSMC's acceleration confirms that runway. The hyperscaler hybrids (META, MSFT) have orthogonal moats (ads / enterprise) that survive a capex cut — same logic that retained GOOGL + AMZN as holds. Governance: **retain-watch**; these are the last to harden-to-short and the names whose *own* backlog/book-to-bill (not GPU sympathy) is the tell.

> Retained as **holds** (not on this list): **GOOGL** (200 sh), **AMZN** (245 sh) — mega-cap hyperscaler hybrids held through their prints (7/22, 7/30). If GOOGL/AMZN capex guides confirm digestion, that is a Tier-3 harden signal for META/MSFT by extension.

---

## Signal classes (the leading indicators)

### Nuance A — The custom-silicon decouple (AVGO)
Hyperscalers are pivoting from merchant GPUs to custom ASICs (Google TPU, Meta MTIA, Amazon Trainium). If NVDA data-center revenue plateaus, don't assume the cycle is dead — capex may be shifting **internal**, which *benefits* AVGO/MRVL. Track AVGO through custom-silicon design wins and networking revenue, **not** NVDA sympathy. Caveat added 2026: the XPU/Apollo vendor-financing structure means AVGO's custom-silicon growth is now partly *circularly financed* — a Signal-E exposure, not a clean decouple.

### Nuance B — The physical power bottleneck (VRT/GEV/CEG, the book-to-bill trap)
The cycle is constrained by the electrical grid, not just packaging. Power names can hold full backlogs even after GPU orders slow — which is why they're Tier 3. **But stock prices trade on the *derivative* of the backlog.** VRT can have 3 years of backlog and still crash if **book-to-bill drops below 1.0** (pipeline draining faster than refilled). Track power/thermal **book-to-bill**, not absolute backlog, in quarterly prints.

### Signal Baseline — Physical cycle: is the hard data confirming yet?
The "are fundamentals catching down to price" check. As long as these are *up*, the exit is front-running and re-entry stays live; when they roll, harden-to-short is confirmed.
- **TSMC monthly revenue** (`get_tsmc_monthly_revenue`) — ~10th of month. Watch YoY decel and unseasonal MoM plateaus; watch commentary on CoWoS advanced-packaging capex (a pause = topping). *Current: accelerating (+67.9% YoY June).*
- **WFE makers** — ASML, AMAT, LRCX guidance (`get_income_statement`, `get_company_news`). An ASML guidance miss is the earliest physical warning of a top (they ship the machines before TSMC expands).
- **Taiwanese ODM monthly sales** — Quanta, Wistron, Wiwynn (~10th, manual, [TWSE MOPS](https://mops.twse.com.tw/mops/web/index)). Unseasonal plateau = hyperscalers tapped the brakes on deliveries.
- **HBM / DRAM spot** — MU is the tool-trackable read (`get_income_statement`, `get_company_news`); spot via TrendForce/DRAMeXchange (manual, [`/briefing` 1g](../.claude/skills)). Spot *declining while contract still rises* = canonical memory rollover; leads MU earnings by 2–3 quarters.

### Signal C — Model-layer commoditization (NEW — the demand ceiling)
The newest and now arguably the #1 leading indicator, and the one the old doc entirely lacked. If the model layer commoditizes without an AGI breakthrough, the labs can't monetize the compute they rent — and the capex chain's end-demand premise fails (see `project_ai_commoditization`).
- **Chinese frontier models** — DeepSeek V4, Moonshot Kimi K3 (2.8T params, largest open-source), Zhipu GLM-5.2, Alibaba Qwen (>50% of global open-source downloads). Now ~30% of global usage at ~1/10th the token cost. Track: new frontier releases, benchmark parity vs OpenAI/Anthropic, enterprise adoption of open weights, token-price collapse. (`get_market_news`, `WebSearch`.)
- **⚠ The Jevons counter (bull refutation — watch for it).** Cheaper intelligence can mean *more* inference → *more* compute, not less. Commoditization is only bearish for the capex chain if cheaper models **fail to expand usage enough to offset the price collapse**. Before hardening on this signal, check whether aggregate inference volume is rising fast enough to keep compute demand intact — if it is, the commoditization read is *wrong* and Tier 2/3 re-entry gets stronger, not weaker. This is the single best argument against the exit; keep it in view.

### Signal E — Capex funding / circular financing (NEW — who pays, and is the money nervous)
The buildout is externally financed; the turn shows up as **funding stress** before order books (see `project_anthropic_circular_financing`, `project_ai_capex_funding_phase`, `project_alarm_window_playbook`). The old doc had nothing here.
- **Neocloud epicenter cohort** — NBIS, IREN, CRWV, APLD (`get_quote`, wired into `/briefing` 1h). Externally-financed demand exists only while capital flows; the epicenter cracks before the generals. Cohort crack (≥3 of 4 down >5%), new 52W lows while SPY holds, or a financing-related single-name collapse (pulled/repriced offering, punitive convert, downgrade) = tripwire.
- **HY credit** — HY OAS is the master switch (`get_bear_regime_score` credit dim, `get_market_regime`). Widening = the marginal financer is repricing risk; the capex chain's cheapest fuel is drying up.
- **Same-issuer issuance terms** — track the *terms*, not the fact, of hyperscaler/neocloud debt (book coverage, new-issue concession, G-spreads on ORCL/AMZN paper). Deteriorating terms same-issuer = early funding stress. (Cross-issuer noise is not the signal.)
- **Mega-IPO distribution** — SpaceX (~$1.75T, SPCX), OpenAI ($852B–$1T), Anthropic ($965B) queued for late-2026. Insiders distributing paper at peak = textbook top window. Watch first-print reactions and lockup calendars (`project_spcx_bearish_entry`, `reference_ipo_lifecycle_playbook`).

### Signal S — Software ROI / depreciation cliff (present-tense now)
The $600B+ capex must be justified by software revenue. **This window is now open, not future** (the old doc said "by late 2026" — it's July 2026).
- **AI software adoption** — Copilot, Agentforce, ServiceNow AI, Adobe Firefly revenue contribution (`get_income_statement` for MSFT, CRM, NOW, ADBE).
- **Hyperscaler operating margins (the depreciation wave)** — 2024–25 GPU capex now depreciating through the P&L over 3–4 years. Compressing op margins with capex still growing = CFOs get forced into cuts. Track MSFT/META/GOOGL op-margin QoQ (`get_income_statement`).
- **The "AI costs more than the humans it replaces" narrative** — the sharper 2026 version of the ROI-ceiling test. If enterprises won't pay because productivity gains don't materialize, the thesis collapses from the demand side.

### Signal G — GPU spot market (now ambiguous — cross-read required)
Falling GPU rental prices used to be a clean canary (excess un-rented capacity → stop buying). **It is no longer clean:** a spot-price drop can be commoditization-driven oversupply (bearish, Signal C) *or* Jevons-driven where cheap compute is being consumed as fast as it's added (bullish). Read it **only** alongside Signal C's inference-volume check. Sources (manual, monthly): [vast.ai](https://vast.ai), [Lambda](https://lambdalabs.com/service/gpu-cloud), [AWS EC2 Spot](https://aws.amazon.com/ec2/spot/pricing/).

### Signal F — Sector breadth / the four-phase unwind (currently flashing)
Parabolic semi rallies unwind from the edges inward. **This is the signal currently yellow** (SMH −10.6% vs SPY = narrowing breadth).
1. **Phase 1 — Everything rips.** Broad rally, small caps lead, SOX runs 18+ days.
2. **Phase 2 — Weakest hands punished.** Slight misses get crushed −10–20%. "Show me the numbers" activates. *(Tier-1 names live here.)*
3. **Phase 3 — Capital concentrates.** Money crowds into 1–3 mega-caps (NVDA, MU) at ATH while mid/small caps bleed. Can last weeks. *(Tier-2 leaders live here.)*
4. **Phase 4 — Last man stumbles.** The final holdout reports "good but not great"; no breadth to cushion; the sector gaps down.

**Track:** ATH concentration ratio (how many of the top-20 semis within 2% of 52W high — narrowing from 10+ to 2–3 = Phase 3); 1-month dispersion (leaders vs laggards spread widening = late cycle); and the asymmetry rule — at ATH the market sells not on deterioration but when **the rate of improvement slows** (second derivative negative). 25% growth priced for 40% is a selloff.

---

## Governance decision tree (replaces the old CC playbook)

Book context: ~81% cash, L2 options (long puts OK; **no** spreads until L3, ~2027 — `project_option_levels`), structural SPY tail hedge already on (`project_portfolio_hedge`).

> **Governing discipline — don't chase.** The cohort can still rip to new ATHs after this exit; that is *expected*, not a refutation. New highs on narrowing breadth are Phase-3 distribution (Signal F) — a higher exit for eventual puts, **never** a re-entry. Re-entry is earned only by a valuation *reset* with fundamentals intact — never by price making new highs. This is the FOMO-Trap circuit breaker (`decision-framework.md`) applied to the entire theme, and the specific failure mode this exit exists to prevent (`feedback_narrative_meltup_trap`).

The three states:

### RE-ENTER (relax a tier to CSP-entry)
**Only two doors open re-entry — at least one must hold. Nothing else qualifies** (not a strong print, not a new ATH, not "it's up a lot"):

1. **Valuation reset** — the froth is out and the name is genuinely *cheap* (multiples compressed to reasonable, not merely off ATH), fundamentals demonstrably intact. This door can open **mid-cycle**: a deep enough individual reset re-qualifies a name even while the broader cycle is still running.
2. **Cycle turn** — the AI-capex cycle has been through a genuine downturn (the exit thesis played out — physical signals rolled over per the Baseline) **and** is *confirmed* bottoming / re-accelerating into a new up-leg. This is the post-washout door for the survivors.

Guardrails on either door: macro not actively deteriorating (bear-regime score not rising through tiers, HY OAS stable); sequence by tier — **Tier 3 first** (power/hybrids), **Tier 2 on a real pullback**, **Tier 1 only on a deep reset**; CSP-as-entry per the growth-first philosophy, scaled in, respecting the cluster cap (`get_cluster_concentration`, 35% of book).

### HOLD PARKED (default)
Signals mixed / fundamentals accelerating but macro hostile — today's state. Do nothing; cash earns the T-bill yield (~4.5%). Powder deploys faster if HY OAS *tightens*, freezes if it *widens*. This is the low-regret default; most months end here.

### HARDEN TO SHORT (L2 long puts — the alarm-window trade)
**Gate hard — requires convergence, not a single flicker:** funding stress firing (Signal E: epicenter cracking AND/OR HY OAS widening) **AND** commoditization confirmed with the Jevons counter *failing* (Signal C: inference volume not offsetting price collapse) **AND** breadth in Phase 4 (Signal F). Only then buy long puts, **Tier 1 names first** (least floor), sized as defined-risk tail bets (long puts bleed theta — this is not a carry position). Cross-reference `alarm-window-playbook.md` and the existing bearish theses (SPCX/QNT/CBRS). Do **not** confuse this with the structural SPY tail hedge, which is trigger-based and never opened on these signals.

### Never
- **Chase strength or a new ATH.** A cohort ripping to new highs is not a re-entry trigger — it is the Phase-3 distribution pattern. The only re-entry is a valuation *reset*, never a breakout. Getting pulled back in by a melt-up is the specific failure this exit exists to prevent.
- **Re-enter on a single strong hyperscaler print** — one green quarter ≠ theme re-arm.
- **Tighten/roll CCs as the primary response** (the old playbook) — the book is no longer long-with-CCs.
- **Deploy powder into a name whose tier hasn't cleared its RE-ENTER gate.**

---

## Cadence

- **Monthly baseline** (10th–15th): TSMC print, WFE/ODM sales, MU/HBM, breadth phase. If Baseline still up → hold parked or continue selective re-entry; if rolling → move toward harden.
- **Event-driven**: earnings cluster (GOOGL 7/22 canary → MSFT/META/QCOM/LRCX 7/29 → AMZN 7/30), any AI mega-IPO first print, an HY-OAS move, a neocloud-cohort crack.
- **Daily (via `/briefing`)**: neocloud epicenter (1h), DRAM spot (1g), bear-regime score (1f) — these are the fast tripwires that pull an event-driven check forward.
