# Cycle Health Check: Leading Indicators for AI Capex Turn

By the time a hyperscaler CEO says "capex moderation" on an earnings call, AVGO and VRT are already down 20% in after-hours. You cannot wait for the official announcement. The covered calls provide a floor, but detecting the turn early lets you tighten strikes, pull expiries closer, and accelerate the exit before the gap-down.

**Run this check monthly (around the 10th-15th). If 2+ signals flash yellow, execute the defensive playbook below.**

## Key Thesis Nuances

### The Custom Silicon Inflection (AVGO)

The semi cycle thesis assumes NVDA and AVGO peak together, but that's wrong. Hyperscalers are actively pivoting from merchant silicon (Nvidia GPUs) toward custom ASICs for inference: Google TPU v7, Meta MTIA, Amazon Trainium 3. A massive chunk of their $600B+ 2026 capex is flowing to in-house chips.

**Impact:** Broadcom is the primary design and networking partner for custom hyperscaler silicon (Google, Meta). If NVDA's data center revenue plateaus, don't assume the whole cycle is dead — it may be hyperscalers shifting capex internally, which *benefits* AVGO. **Decouple AVGO's thesis timeline from pure GPU metrics.** Track AVGO through custom silicon design wins and networking revenue, not NVDA sympathy.

### The Physical Power Bottleneck (VRT)

In 2026, the AI capex cycle is constrained not just by TSMC packaging capacity but by the electrical grid itself. Gas turbines and transformers are backlogged for years.

**Impact:** The cycle might plateau because hyperscalers physically cannot procure the megawatts to plug in new clusters. If data center permitting slows due to grid constraints, hardware orders follow. This makes VRT potentially the *last* to roll over, not the first — its backlog stays full even after GPU orders slow. VRT is both a leading indicator for new construction AND a beneficiary of physical constraints that extend the power buildout timeline beyond the silicon cycle.

**Book-to-Bill trap:** Stock prices trade on the *derivative* of the backlog, not its absolute size. VRT can have 3 years of backlog and still crash if the Book-to-Bill ratio (new orders received / orders billed) drops below 1.0 — that means the pipeline is draining faster than it's being replenished. Wall Street is forward-looking: a declining book-to-bill signals the growth inflection has passed, regardless of remaining backlog. Track power/thermal book-to-bill ratios in quarterly earnings, not just absolute backlog figures.

## Signal 1: Cloud Compute Spot Market (canary in the coal mine)

Hyperscalers buy GPUs to rent them out. If rental demand softens, buying stops.

- **GPU rental lead times**: If securing a large GPU cluster from AWS/Azure drops from months to days/weeks, supply has caught up to demand.
- **Spot pricing for compute**: Track hourly rates for GPU instances (AWS P5, Azure ND H100) on spot/secondary markets. Aggressively dropping spot prices = excess un-rented capacity. Why buy more hardware if current hardware sits idle?

*Manual research — check monthly:*
- [vast.ai](https://vast.ai) — peer-to-peer GPU marketplace, best real-time pricing aggregator
- [Lambda Labs](https://lambdalabs.com/service/gpu-cloud) — GPU cloud pricing
- [AWS EC2 Spot](https://aws.amazon.com/ec2/spot/pricing/) — P5/P4d spot pricing history

## Signal 2: Upstream Supply Chain & ODMs

The companies that actually build the servers and chips report earlier and more frequently than their hyperscaler customers.

- **Wafer Fab Equipment (WFE) makers**: ASML, Applied Materials (AMAT), Lam Research (LRCX). These are the *true* upstream — before TSMC can expand CoWoS capacity, they must order the machines to do it. If TSMC or Samsung cancels or delays tool orders, it shows up in ASML guidance months before TSMC's own revenue dips. An ASML guidance miss is the earliest physical warning of a cycle top. *(Tool: `get_income_statement`, `get_company_news` — all US-listed with full data.)*
- **TSMC monthly revenue**: Reported monthly. Watch for unseasonal plateaus or declines. More importantly, watch CoWoS advanced packaging capacity — if TSMC pauses its own capex for expanding CoWoS, the cycle is topping. TSM ADR is tool-trackable for quarterly financials; monthly revenue requires manual check at [investor.tsmc.com](https://investor.tsmc.com/english).
- **Taiwanese ODM monthly sales**: Quanta, Wistron, Wiwynn report sales around the 10th of every month. A sudden, unseasonal plateau in monthly revenue growth = hyperscalers quietly tapped the brakes on deliveries. *(Manual research — Taiwan-listed, no US data. Check [TWSE MOPS](https://mops.twse.com.tw/mops/web/index) for mandatory monthly filings.)*
- **SMCI revenue trajectory**: Already volatile, but a sustained downturn here leads the broader semi space. *(Tool: `get_income_statement`, `get_company_news`.)*

## Signal 3: Memory Pricing (HBM)

High-Bandwidth Memory is attached to every AI accelerator. Memory is notoriously cyclical and sensitive to demand shocks.

- **HBM spot pricing**: If spot prices for HBM start softening, GPU production is slowing. *(Manual research — [TrendForce](https://trendforce.com) publishes DRAM/HBM pricing trends; detailed data is paywalled but free bulletins cover headline moves.)*
- **Memory maker guidance**: MU is the primary tool-trackable read. SK Hynix and Samsung are Korea-listed with no usable US data — track their guidance via `get_company_news` for MU (which references competitors) and general market news. *(Tool: `get_income_statement`, `get_earnings_calendar`, `get_company_news` for MU.)*
- **MU is in the portfolio** — its earnings calls and guidance are a direct read on HBM demand.

## Signal 4: Networking & Power (edge fraying)

Semi cycles rarely turn all at once — the edges fray first, then the core.

- **Optical transceivers & networking**: Coherent (COHR), Lumentum (LITE), Marvell (MRVL). If they guide down, GPUs are next. CRDO connectivity is a direct read here. *(Tool: all US-listed with full data.)*
- **Data center power equipment**: Eaton (ETN), Vertiv (VRT). If backlog for data center thermal management and power delivery stops growing, new data center construction is slowing. VRT is the canary for this subsector. *(Tool: all US-listed with full data.)*

## Signal 5: Software ROI Check (the fundamental ceiling)

The $690B+ in AI infra capex must eventually be justified by software revenue. If enterprise AI adoption stalls, hyperscaler CFOs will pull the plug.

- **Watch Phase 3 AI software adoption**: Microsoft Copilot adoption numbers, ServiceNow AI agents, Salesforce Agentforce, Adobe Firefly revenue contribution. *(Tool: `get_income_statement` for MSFT, CRM, NOW, ADBE — all US-listed.)*
- **Hyperscaler operating margins (depreciation cliff)**: The $600B+ in 2024-2025 GPU/infra capex goes on the balance sheet as an asset, then depreciates through income statements over 3-4 years. By late 2026, this depreciation wave hits MSFT/META/GOOG operating margins hard. If AI software revenue (Copilot, Agentforce) hasn't scaled to offset the depreciation expense, margins compress. When Wall Street sees margin compression with capex still growing, CFOs get forced into cuts. Track hyperscaler operating margins quarter-over-quarter — expanding margins = AI monetization working, compressing margins = depreciation outrunning revenue. *(Tool: `get_income_statement` for MSFT, META, GOOG — compare operating margin trends.)*
- **The test**: If multiple quarters pass and enterprises refuse to pay for AI tools because productivity gains aren't materializing, the infrastructure investment thesis collapses from the demand side.

## Defensive Playbook (when 2+ signals flash yellow)

| Action | Detail |
|--------|--------|
| **Tighten CC strikes** | Roll existing CCs to closer-to-ATM strikes — accept less upside to lock in more downside protection |
| **Pull CC expiries closer** | Roll from Dec '26/Jan '27 to shorter-dated expiries — accelerate the exit |
| **Stop rolling CSPs** | On any Phase 1 names, let existing CSPs expire. Don't write new ones. |
| **Accelerate LEAPS exits** | NVDA Jan '27 LEAPS — if signals fire before earnings catalyst (5/27), close for whatever profit exists rather than holding into a gap-down |
| **Rotate into Phase 3** | Begin CSP pipeline on software/application winners (ADBE, CRM, FTNT) at fear-compressed valuations |
| **Portfolio hedges** | Activate QQQ bear put spreads (Category A from L3 plan) |
