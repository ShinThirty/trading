"""Tests for the FactSet Earnings Insight filename resolution.

FactSet usually publishes ``EarningsInsight_<MMDDYY>.pdf`` but some weeks carry
an ``A`` suffix (the May 29 2026 report was only posted as
``EarningsInsight_052926A.pdf`` — the plain name 404s). The day-walk must try
both variants per day, or it silently falls back to a week-stale report.
"""

from datetime import date

from trading_clients.factset_client import _filenames_for


def test_filenames_for_tries_plain_then_suffixed() -> None:
    # May 29 2026 — plain name 404s in the wild; the A variant is the live PDF.
    assert _filenames_for(date(2026, 5, 29)) == (
        "EarningsInsight_052926.pdf",
        "EarningsInsight_052926A.pdf",
    )


def test_filenames_for_plain_comes_first() -> None:
    # Historical default order is preserved: plain name is preferred when both
    # exist, so weeks like May 21 (plain-only) keep resolving as before.
    names = _filenames_for(date(2026, 5, 21))
    assert names[0] == "EarningsInsight_052126.pdf"
    assert names[1] == "EarningsInsight_052126A.pdf"
