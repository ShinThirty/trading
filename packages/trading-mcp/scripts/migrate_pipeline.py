#!/usr/bin/env python3
# ruff: noqa: E501
"""One-time migration: import pipeline entries from Claude Code memory files into trading.db."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "trading-clients" / "src"))

from trading_mcp.db import open_db
from trading_mcp.pipeline_store import _add_entry, _get_active_entry, init_schema

MEMORY_DIR = Path.home() / ".claude/projects/-Users-shinthirty-Workspaces-trading/memory"

WEBULL_TICKERS = {
    "ADBE", "PTC", "NVDA", "MU", "INOD", "UBER", "RCL", "NFLX", "TSM",
    "FTNT", "LRCX", "QCOM", "CHKP", "PAYC", "LSCC", "WOLF", "CRWV",
    "AMZN", "CBRS", "ADI", "PAYX",
}
FIDELITY_TICKERS = {
    "PANW", "MSFT", "V", "INTU", "LDOS",
}

ENTRIES = [
    {
        "ticker": "ADBE", "intent": "accumulate", "status": "LIVE", "tier": "full",
        "conviction": "highest", "pe": 14.1, "peg": 1.18, "roe": 62.3, "de": 0.53,
        "drawdown_pct": -41.8, "rev_growth": 12.0, "earnings_date": "2026-06-11",
        "thesis": "Creative suite monopoly with expanding margins (36.7→37.8%), Firefly AI platform competitiveness mispriced. Deep discount at 52W low vs elite profitability.",
        "position": "1x $180C Jan '27 LEAPS + 2x $200C Jun '27 LEAPS @ $76.98. Total ~$28K deployed, ~241 shares delta equiv.",
        "entry_plan": "T1 LEAPS filled. T2 CSP (2 contracts) June 18 expiry post-earnings, target $210-220P if price ~$246.",
        "management": "LEAPS hold through earnings cycles. CSP close at 50% profit. Reassess if drops >15%.",
    },
    {
        "ticker": "PTC", "intent": "accumulate", "status": "LIVE", "tier": "full",
        "conviction": "highest", "pe": 21.7, "peg": 1.01, "roe": 22.5, "de": 0.31,
        "drawdown_pct": -39.0, "rev_growth": 21.4, "earnings_date": "2026-05-06",
        "thesis": "Industrial CAD/PLM/ALM moat (BMW enterprise-wide Codebeamer win). Zero SaaSpocalypse exposure — AI is upsell, not displacement. PEG 1.01 is best in pipeline.",
        "position": "40 shares @ ~$135-136 (4/15).",
        "entry_plan": "T1 40 shares filled. T2 post-May 6 earnings CSP (~$115-120P). T3 scale-in if >8% drop.",
        "management": "No hard stop loss at highest conviction. Scale-in T3 at 8% drop. Close CSP at 50% profit.",
    },
    {
        "ticker": "NFLX", "intent": "accumulate", "status": "LIVE", "tier": "standard",
        "conviction": "highest", "roe": 49.0, "de": 0.54, "rev_growth": 16.0,
        "account": "Webull Individual Cash",
        "thesis": "Streaming monopoly with 300M+ subs, deep switching costs, expanding margins (32.3%). Ad revenue is $3B+ growth lever.",
        "position": "200 shares @ $94.83 + 2x $95P May 29 @ $2.38 + 2x $90P Jun 18 @ $2.50 limit GTC.",
        "entry_plan": "CSP harvest to 50% profit or assignment. Remaining ~59 shares (T3) reserved for dip to $88-90.",
        "management": "Q1 beat ($1.23 vs $0.76). Monitor Q2 guidance for conviction reassessment.",
    },
    {
        "ticker": "NVDA", "intent": "accumulate", "status": "WAITING", "tier": "full",
        "conviction": "high", "pe": 39.8, "peg": 0.64, "roe": 104.4, "de": 0.05,
        "drawdown_pct": -5.3, "rev_growth": 62.1,
        "thesis": "AI infrastructure monopoly with GPU moat + CUDA ecosystem. Expanding margins (55%→58%). Deeply undervalued by PEG despite high P/E.",
        "position": "2x $150C Jan '27 LEAPS (~$12.7K, 1.0% of portfolio).",
        "entry_plan": "Hold current LEAPS. Trigger add on SPY RSI <65 and/or >10% pullback from highs.",
        "management": "Only -5.3% from highs, no discount yet. Wait for broad market cooldown.",
    },
    {
        "ticker": "MU", "intent": "accumulate", "status": "WAITING", "tier": "full",
        "conviction": "high", "pe": 60.6, "peg": 0.49, "roe": 40.8, "de": 0.27,
        "drawdown_pct": -3.3, "rev_growth": 123.7,
        "thesis": "HBM memory leader with rapidly expanding margins (23.5%→59.4%). PEG 0.49 is best in portfolio. AI-driven HBM demand is structural.",
        "position": "110 shares (~$50K, 4.0%): 10 standalone + 100 covered by 1x $500C Jan '27.",
        "entry_plan": "Hold current. Trigger add on SPY RSI <65 and/or >10% pullback.",
        "management": "Only -3.3% from 52W high. Wait for broad market cooldown.",
    },
    {
        "ticker": "INOD", "intent": "accumulate", "status": "WAITING", "tier": "full",
        "conviction": "highest", "pe": 47.0, "peg": 0.77, "roe": 35.1,
        "de": 0.0, "rev_growth": 61.0, "earnings_date": "2026-05-07",
        "thesis": "AI data labeling picks-and-shovels with hyperscaler + DoD/Palantir contracts. Zero debt, FCF accelerating ($5.9M→$35M→$46.8M).",
        "entry_plan": "Post-May 7 earnings. Hybrid, shares-heavy (IV Rank 62%). Beat + pullback = CSP at support. Beat + gap up = buy pullback.",
        "management": "Beta 2.55, small cap ($1.5B), customer concentration risk.",
    },
    {
        "ticker": "UBER", "intent": "accumulate", "status": "WAITING", "tier": "standard",
        "conviction": "highest", "pe": 15.6, "peg": 1.84, "roe": 40.3, "de": 0.39,
        "drawdown_pct": -24.4, "rev_growth": 18.0, "earnings_date": "2026-05-06",
        "thesis": "Robotaxi narrative flipped from threat to platform core. 40% ROE at 15.6x P/E with massive revenue growth. $10B robotaxi commitment.",
        "entry_plan": "Hybrid LEAPS+shares. T1: 8x $70C Jan '28 LEAPS @ ~$22 each (~$18K). T2-T3: ~240 shares each on dips or post-May 6 earnings.",
        "management": "LEAPS spreads tight (2.9%) despite Liq 4. Post-May 6 earnings trigger entry. Standard tier = 5% = $55K target.",
    },
    {
        "ticker": "RCL", "intent": "accumulate", "status": "WAITING", "tier": "standard",
        "conviction": "highest", "roe": 46.0, "de": None, "peg": 2.42,
        "drawdown_pct": -23.0, "rev_growth": 29.0, "earnings_date": "2026-04-30",
        "thesis": "Consumer discretionary services (no tariff exposure). 46% ROE, 29% op margin expanding, FCF $1.1B. CEO reports exceptionally high demand.",
        "entry_plan": "Wait for 4/30 earnings. Post-earnings: beat+positive guidance → CSP $250P May 29 or LEAPS.",
        "management": "Non-tech diversification. IV Pctl 98.3% (post-earnings IV crush improves CSP economics).",
    },
    {
        "ticker": "PAYX", "intent": "accumulate", "status": "LIVE", "tier": "full",
        "conviction": "highest", "peg": 1.12, "roe": 41.0, "drawdown_pct": -42.0,
        "rev_growth": 18.0, "account": "Webull Cash + Fidelity",
        "thesis": "Payroll infrastructure compounder, regulatory moat, 40% op margins. AI enhances services, doesn't displace. $1B buyback announced.",
        "position": "25 shares @ $95.03 + 1x $85P Jun 18 CSP @ $1.65 (Webull Cash).",
        "entry_plan": "T2: Scale in via Fidelity CSP on dip or post-late June earnings.",
        "management": "CSP manage to 50% profit ($0.83). Next earnings ~late June.",
    },
    {
        "ticker": "ADI", "intent": "accumulate", "status": "WAITING", "tier": "standard",
        "conviction": "moderate", "pe": 76.2, "peg": 2.50, "roe": 7.9, "de": 0.25,
        "drawdown_pct": 0.0, "rev_growth": 30.4,
        "thesis": "Analog/mixed-signal semi leader. Cyclical recovery. Margins expanding (20.3%→31.5%), zero debt.",
        "position": "27 shares (~$10K, 0.8%).",
        "entry_plan": "Hold current. Trigger add on SPY RSI <65 and/or >10% pullback from highs.",
        "management": "At ATH. ROE 7.9% is lowest of all add candidates — lower priority.",
    },
    {
        "ticker": "TSM", "intent": "enter-at-discount", "status": "WAITING", "tier": "standard",
        "conviction": "high", "pe": 31.4, "peg": 1.5, "roe": 35.1, "de": 0.18,
        "drawdown_pct": -5.5, "rev_growth": 20.0,
        "thesis": "Foundry monopoly. Expanding margins (48.5%→54.0%). Semi cycle thesis extended to early-mid 2027 directly benefits TSMC.",
        "entry_plan": "Q1 beat + guidance raised (4/16). Trigger: SPY RSI <65 and/or pullback to $340-350.",
        "management": "Only -5.5% from highs, not discount.",
    },
    {
        "ticker": "FTNT", "intent": "enter-at-discount", "status": "WAITING", "tier": "standard",
        "conviction": "high", "pe": 31.35, "peg": 2.2, "roe": 123.64, "de": 0.81,
        "drawdown_pct": -27.0, "rev_growth": 14.0, "earnings_date": "2026-05-06",
        "thesis": "Best cybersecurity financials — 124% ROE, 80% gross margins, 14% rev growth, margins expanding. AI makes cybersecurity MORE important.",
        "entry_plan": "Post-May 6 earnings CSP June 18 (~$65-70 strike, ~$7K collateral).",
        "management": "Zero-day + Mizuho downgrade + OpenAI cyber threat headwinds. Stock held $77 support = resilience signal.",
    },
    {
        "ticker": "LRCX", "intent": "enter-at-discount", "status": "WAITING", "tier": "standard",
        "conviction": "high", "pe": 60.9, "peg": 2.45, "roe": 62.6, "de": 0.45,
        "drawdown_pct": -2.0, "rev_growth": 24.9, "earnings_date": "2026-04-22",
        "thesis": "WFE picks-and-shovels for AI capex cycle. Aligned with semi cycle thesis. IV Rank 76.2% + Liq 2 = best premium-selling setup.",
        "entry_plan": "Post-Apr 22 earnings pullback. CSP June 18, 1 contract, target $260-280P.",
        "management": "Only -2% from highs after +22% 10-day rally. Wait for sell-the-news dip with IV crush.",
    },
    {
        "ticker": "QCOM", "intent": "harvest-premium", "status": "WAITING", "tier": "standard",
        "conviction": "moderate", "pe": 24.6, "peg": 2.2, "roe": 21.6,
        "rev_growth": 5.0, "earnings_date": "2026-04-29",
        "thesis": "Edge AI thesis real but unproven in revenue (5% growth, margins compressing 30.5%→27.5%). IV-HV +17.2% = premium priced at 2x actual volatility.",
        "entry_plan": "Wait for Apr 29 earnings. Post-earnings CSP May or June (target $110-120P range).",
        "management": "Harvest premium only; do not accumulate until revenue re-accelerates.",
    },
    {
        "ticker": "CHKP", "intent": "harvest-premium", "status": "WAITING", "tier": "full",
        "conviction": "moderate", "pe": 13.25, "roe": 36.62, "de": 0.68,
        "drawdown_pct": -42.0, "rev_growth": 6.0, "earnings_date": "2026-04-30",
        "thesis": "13.25x P/E with 36.6% ROE looks cheap but 6% growth explains discount. Margin compression. 97.2% IV Rank = near-max premium.",
        "entry_plan": "Post-Apr 30 earnings June 18 CSP (~$110-120P). Use sector result as leading indicator for FTNT/PAYC.",
        "management": "Harvest premium only. Do not accumulate unless revenue growth re-accelerates >10%.",
    },
    {
        "ticker": "PAYC", "intent": "harvest-premium", "status": "WAITING", "tier": "full",
        "conviction": "moderate", "pe": 14.67, "roe": 26.06, "de": 0.0,
        "drawdown_pct": -54.0, "rev_growth": 8.5, "earnings_date": "2026-05-06",
        "thesis": "Downgraded from enter-at-discount due to margin compression (35%→27%). Zero debt + 6.5% FCF yield + $526M buybacks provide floor. 93.4% IV Rank.",
        "entry_plan": "Post-May 6 earnings June 18 CSP target $95-105P range (~$10K collateral per contract, 2 contracts = full tier).",
        "management": "Harvest premium only; watch margin trend. If margins stabilize >30%, upgrade to enter-at-discount.",
    },
    {
        "ticker": "LSCC", "intent": "bearish", "status": "WAITING", "tier": "reduced",
        "conviction": "high", "pe": 5195.0, "roe": 0.4, "rev_growth": -3.7,
        "earnings_date": "2026-05-04",
        "thesis": "Business fundamentally deteriorating (ROE collapse, rev decline, margins -12%→-1%) but AI/defense narrative inflated valuation 169%.",
        "entry_plan": "Post-May 4 earnings: if margins continue collapsing + IV <30%, long put -0.40 delta 45-60 DTE.",
        "management": "Max 3% portfolio (bearish sizing). If margins stabilize, thesis broken, skip.",
    },
    {
        "ticker": "WOLF", "intent": "bearish", "status": "WAITING", "tier": "reduced",
        "conviction": "high", "de": 7.0, "earnings_date": "2026-05-06",
        "thesis": "6/6 deterioration signals. Revenue declining, gross margins -39%, op margins -82%, D/E 7x, negative equity, cash burn $469M/9mo. Structurally high IV (120%+) makes puts expensive.",
        "entry_plan": "Post-May 6 earnings: if margins still negative despite refinancing, enter -0.30 delta 60 DTE. If revenue inflects, skip.",
        "management": "Max 3% portfolio. Needs absolute IV compression or L3 spreads to be viable.",
    },
    {
        "ticker": "CRWV", "intent": "bearish", "status": "WAITING", "tier": "reduced",
        "conviction": "low", "de": 6.48, "earnings_date": "2026-05-13",
        "thesis": "Revised from bearish to direction-neutral post-gap straddle. Jane Street $6B cloud + $1B equity adds headline risk. Insider selling pattern persists.",
        "entry_plan": "Post-May 13 earnings: day after gap, enter ATM straddle, May 22 expiry. Exit half day 5, rest by day 10. 1 contract max.",
        "management": "Liquidity 4 (worst spreads) is biggest execution risk. Use limit orders only.",
    },
    {
        "ticker": "PANW", "intent": "enter-at-discount", "status": "LIVE", "tier": "standard",
        "conviction": "high", "roe": 124.0,
        "account": "Fidelity BrokerageLink Roth",
        "thesis": "High-conviction cybersecurity with 124% ROE. Zero-day vulnerability was near-term headwind but doesn't change thesis.",
        "position": "1x $155P May 15 sold @ $2.62. Currently underwater. Assignment is the plan.",
        "entry_plan": "Assignment at $155 → effective cost $152.38. Post-assignment, evaluate CC overlay.",
        "management": "Do not close this CSP. Assignment is intended outcome.",
    },
    {
        "ticker": "MSFT", "intent": "enter-at-discount", "status": "LIVE", "tier": "standard",
        "conviction": "high", "peg": 1.82, "roe": 33.6, "de": 0.26,
        "drawdown_pct": -23.7, "rev_growth": 16.7,
        "account": "Fidelity BrokerageLink", "earnings_date": "2026-04-29",
        "thesis": "Fortress balance sheet with expanding margins. 30% off 52W high on a monopoly in tax-advantaged account.",
        "position": "1x $400P May 29 @ $9.39 ($938 credit) filled 4/17.",
        "entry_plan": "Close at 50% profit. If assigned: hold long-term in Roth, evaluate CC overlay.",
        "management": "IV Rank 89.6%, IV-HV +12.7%. Assignment at $390.80 effective.",
    },
    {
        "ticker": "V", "intent": "accumulate", "status": "LIVE", "tier": "full",
        "conviction": "highest", "pe": 29.8, "peg": 2.04, "roe": 54.2, "de": 0.66,
        "drawdown_pct": -16.4, "rev_growth": 14.6,
        "account": "Fidelity Roth", "earnings_date": "2026-04-28",
        "thesis": "Capital-light monopoly. Payment rails for global commerce + AI agentic commerce + stablecoin infrastructure. 54% ROE on 0.66 D/E, 62% op margins, 0.80 beta.",
        "position": "25 shares @ $310 (Roth). Remaining: 25 more shares + 2x $330C Jan '28 LEAPS post-Apr 28 earnings.",
        "entry_plan": "T1 LEAPS post-Apr 28 earnings (~$8.7K). T2 CSP post-earnings ~$290-300P strike.",
        "management": "DOJ antitrust case + FTC debanking scrutiny (regulatory overhang). Target $31.1K deployment.",
    },
    {
        "ticker": "INTU", "intent": "accumulate", "status": "LIVE", "tier": "standard",
        "conviction": "highest", "pe": 19.0, "peg": 1.58, "roe": 22.0,
        "drawdown_pct": -51.7, "rev_growth": 18.0,
        "account": "Fidelity BrokerageLink Roth", "earnings_date": "2026-05-28",
        "thesis": "SaaSpocalypse selloff (-52%) is narrative risk, not fundamental. Revenue accelerating, margins expanding, CEO buying back aggressively.",
        "position": "1x $350C Jan '28 LEAPS @ ~$131 filled 4/20 (~$13.1K).",
        "entry_plan": "T2: Post-May 28 earnings CSP (30-45 DTE, ~$35K collateral). T3: Scale on further pullback <$350.",
        "management": "Margins expanding despite SaaSpocalypse narrative. CEO halted insider sales + accelerated buyback.",
    },
    {
        "ticker": "LDOS", "intent": "enter-at-discount", "status": "WAITING", "tier": "standard",
        "conviction": "high", "pe": 13.5, "roe": 30.0, "de": 0.95,
        "drawdown_pct": -24.6, "rev_growth": 5.0, "earnings_date": "2026-05-05",
        "thesis": "Sector diversification (defense tech). Beta 0.62 uncorrelated. P/E 13.5 at 30% ROE is genuinely cheap. IV Rank 85%.",
        "entry_plan": "Post-May 5 earnings CSP ~$135-140 strike, 30-45 DTE (~$14K collateral if assigned).",
        "management": "Standard tier by sizing. D/E 0.95 moderate. 1.11% dividend. Hold for decades post-assignment.",
    },
    {
        "ticker": "AMZN", "intent": "exit", "status": "LIVE", "tier": "full",
        "conviction": "highest",
        "thesis": "Largest single-stock position (~18% of main account, ~$205K). No longer wants shares called at $225C.",
        "position": "800 shares covered by $250C 12/18 CC (rolled 4/10 for $2.50 credit = $2,000). 45 naked shares remain uncovered.",
        "entry_plan": "Monitor for further rolls if stock approaches $250.",
        "management": "Keep AMZN exposure long-term. Plan change based on semiconductor recovery strength.",
    },
    {
        "ticker": "CAR", "intent": "bearish", "status": "WAITING", "tier": "reduced",
        "conviction": "high", "de": 22.0, "earnings_date": "2026-05-06",
        "thesis": "Post-squeeze play. Negative earnings, D/E 22x, revenue -1% YoY. Squeeze active + IV Rank 100% block entry. AMC 2021 playbook.",
        "entry_plan": "Entry triggers (ALL must be met): RSI <50, daily volume 1-2M with failing bounces, SI declining from 26%, IV Rank <70%. Long puts -0.30 to -0.40 delta, 45-60 DTE.",
        "management": "Short interest 26% SI of float. Max 3% portfolio.",
    },
    {
        "ticker": "CPAY", "intent": "watchlist", "status": "WAITING", "tier": "standard",
        "conviction": "highest", "pe": 21.3, "peg": 1.84, "roe": 27.9, "de": 2.58,
        "drawdown_pct": -7.6, "rev_growth": 11.6, "earnings_date": "2026-05-05",
        "thesis": "Fleet card lock-in, AP workflow integration, 800K+ business clients. All 4 Bullish factors (rare). Only -7.6% off highs, Front-Run Catalyst active.",
        "entry_plan": "Post-May 5 earnings pullback to -15%+ (~$305). Broader market selloff as alternative trigger.",
        "management": "Highest conviction but need pullback. If V fills first, CPAY is secondary.",
    },
    {
        "ticker": "CBRS", "intent": "ipo-momentum", "status": "WAITING", "tier": "reduced",
        "conviction": "low",
        "thesis": "Momentum trade on 'NVIDIA killer' retail FOMO. S-1 shows problematic fundamentals: 86% UAE concentration, operating loss -$145.9M FY2025, gross margin declining.",
        "entry_plan": "IPO allocation preferred. Exit triggers: ~10 trading days post-IPO OR 15-20% trailing stop. No averaging down.",
        "management": "Reduced tier, short hold only. Long-term hold thesis does NOT exist.",
    },
    {
        "ticker": "WDAY", "intent": "harvest-premium", "status": "CLOSED",
        "conviction": "low", "pe": None, "peg": 3.49, "roe": 14.5,
        "thesis": "Permanently removed. PEG 3.49, op margin 7.8%. HR workflows highly automatable by AI agents.",
        "management": "Do NOT re-enter. Permanently exited.",
    },
    {
        "ticker": "NOW", "intent": "accumulate", "status": "SKIP",
        "conviction": "low", "pe": 58.0, "roe": 15.4, "drawdown_pct": -54.0,
        "thesis": "Value trap. -54% drawdown but moat under active AI displacement threat. ROE 15.4% (mediocre). Op margins choppy.",
        "management": "Permanently SKIPPED. Capital better deployed on ADBE/MU/NVDA.",
    },
    {
        "ticker": "TSLA", "intent": "accumulate", "status": "SKIP",
        "conviction": "negative", "pe": 396.0, "roe": 4.8, "rev_growth": -2.9,
        "thesis": "Framework rejects. ROE 4.8%, P/E 396x, revenue declining. AI/robotaxi/Optimus unmonetized. BYD 3x bigger globally.",
        "management": "Do not write CSPs or accumulate. Reassess only if robotaxi/FSD show real revenue + margin improvement.",
    },
    {
        "ticker": "ARM", "intent": "bearish", "status": "SHELVED",
        "conviction": "moderate", "pe": 211.0,
        "thesis": "IP licensing business at 211x P/E. RISC-V + custom silicon threats. No L3 until 2027 (bear call spreads unavailable). No reliable post-earnings bleed pattern.",
        "management": "Revisit if L3 approved (2027) or ARM develops consistent post-earnings bleed pattern.",
    },
    {
        "ticker": "BTC", "intent": "accumulate", "status": "LIVE",
        "conviction": "moderate", "account": "Strike",
        "thesis": "Slow DCA accumulation via weekly buys. Contrarian entry on drawdowns.",
        "position": "Ongoing weekly buys (~$200/week baseline, scaled by drawdown from ATH).",
        "entry_plan": "DCA scaling: >50% DD = $400/week (2x); 30-50% DD = $200/week; 15-30% DD = $150/week; <15% DD = $100/week.",
        "management": "$60K floor — if broken, re-evaluate leverage cascade thesis.",
    },
]


def main() -> None:
    conn = open_db()
    init_schema(conn)

    added = 0
    skipped = 0

    for data in ENTRIES:
        ticker = data["ticker"]

        # Assign pipeline
        if "pipeline" not in data:
            if ticker in FIDELITY_TICKERS:
                data["pipeline"] = "fidelity"
            elif ticker in WEBULL_TICKERS:
                data["pipeline"] = "webull"

        existing = _get_active_entry(conn, ticker)
        if existing:
            print(f"  SKIP  {ticker} (already exists, id={existing['id']})")
            skipped += 1
            continue

        # Filter None values for fields that don't accept them
        clean = {k: v for k, v in data.items() if v is not None}

        try:
            entry = _add_entry(conn, clean)
            print(f"  ADD   {ticker} (id={entry['id']}, {entry['intent']}, {entry['status']})")
            added += 1
        except Exception as e:
            print(f"  ERR   {ticker}: {e}")

    conn.close()
    print(f"\nDone: {added} added, {skipped} skipped")


if __name__ == "__main__":
    main()
