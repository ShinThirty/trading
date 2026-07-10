"""Fidelity positions-CSV parsing.

Fidelity has shipped this export with both Title Case ("Current Value") and
Sentence case ("Current value") column headers. The parser must match headers
case-insensitively — a case flip previously slipped past the required-column
check and silently dropped the ENTIRE file from the book (a $0-Fidelity
denominator that inflated every cluster-cap read).

Also pins the BrokerageLink roll-up behavior: a 401k's "BROKERAGELINK" line is
the sum of sub-accounts enumerated separately, so it must be skipped rather than
double-counted.
"""

# ruff: noqa: E501  — CSV fixture rows are inherently wider than the line limit.
import asyncio

from trading_clients.portfolio import parse_fidelity_csv

# Sentence-case headers (the format that regressed) + an embedded comma in a
# quoted account name + a BrokerageLink roll-up whose sub-accounts follow.
_SENTENCE_CASE_CSV = """\
Account number,Account name,Symbol,Description,Quantity,Last price,Last price change,Current value,Today's gain/loss dollar,Today's gain/loss percent,Total gain/loss dollar,Total gain/loss percent,Percent of account,Cost basis total,Average cost basis,Type
33363,"CONFLUENT, INC.",VINIX,VANGUARD INST INDEX,28.412,$606.49,+$2.60,$17231.59,+$73.87,+0.43%,+$5263.38,+43.98%,100.00%,$11968.21,$421.24,,
33363,"CONFLUENT, INC.",,BROKERAGELINK,300000,$1.00,$0.00,$300000.00,$0.00,0.00%,$0.00,0.00%,--,$300000.00,$1.00,,
653534787,BrokerageLink,FDRXX**,HELD IN MONEY MARKET,,,,$100000.00,,,,,72.6%,,,Cash,
653534787,BrokerageLink,QCOM,QUALCOMM INC,200,$189.16,-$1.95,$37832.00,-$390.00,-1.03%,-$1703.41,-4.31%,27.4%,$39535.41,$197.68,Cash,
653534788,BrokerageLink Roth,V,VISA INC,100,$348.97,+$0.77,$34897.00,+$77.00,+0.22%,+$2414.00,+7.43%,100.28%,$32483.00,$324.83,Cash,
653534788,BrokerageLink Roth, -CRDO260710P250,CRDO JUL 10 2026 $250 PUT,-3,$0.45,-$1.52,-$135.00,+$456.00,+77.15%,+$5692.87,+97.68%,-0.28%,$5827.87,$19.43,Cash,

"The data and information in this spreadsheet is provided to you solely for your use and is not for distribution."

"Date downloaded Jul-10-2026 6:05 p.m ET"
"""


def _write(tmp_path, text: str) -> str:
    p = tmp_path / "Portfolio_Positions_Jul-10-2026.csv"
    p.write_text(text, encoding="utf-8-sig")
    return str(p)


def test_sentence_case_headers_parse_and_skip_brokeragelink_rollup(tmp_path):
    accts = asyncio.run(parse_fidelity_csv(_write(tmp_path, _SENTENCE_CASE_CSV)))

    by_id = {a.account_id: a for a in accts}
    assert set(by_id) == {"33363", "653534787", "653534788"}

    # 401k: only VINIX counts — the $300k BROKERAGELINK roll-up is skipped, not
    # counted as cash (its holdings are the two sub-accounts below).
    assert round(by_id["33363"].nlv, 2) == 17_231.59
    assert round(by_id["653534787"].nlv, 2) == 137_832.00  # FDRXX cash + QCOM
    assert round(by_id["653534788"].nlv, 2) == 34_762.00  # V equity − short put

    # Grand total excludes the roll-up (would be off by $300k if double-counted).
    assert round(sum(a.nlv for a in accts), 2) == 189_825.59


def test_title_case_headers_still_parse(tmp_path):
    title = _SENTENCE_CASE_CSV.replace(
        "Account number,Account name,Symbol,Description,Quantity,Last price,Last price change,"
        "Current value,Today's gain/loss dollar,Today's gain/loss percent,Total gain/loss dollar,"
        "Total gain/loss percent,Percent of account,Cost basis total,Average cost basis,Type",
        "Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,"
        "Current Value,Today's Gain/Loss Dollar,Today's Gain/Loss Percent,Total Gain/Loss Dollar,"
        "Total Gain/Loss Percent,Percent Of Account,Cost Basis Total,Average Cost Basis,Type",
    )
    accts = asyncio.run(parse_fidelity_csv(_write(tmp_path, title)))
    assert round(sum(a.nlv for a in accts), 2) == 189_825.59
