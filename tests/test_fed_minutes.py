"""Tests for FOMC calendar minutes-link discovery and the minutes section splitter.

Fed minutes markup shifts across years (Attendance at the top in 2024, at the
bottom in 2026; the meeting-date line sometimes its own bolded paragraph) —
these tests pin the structural rules so a refactor that breaks real pages
fails loudly.
"""

from trading_clients.endpoints.fed import (
    FomcCalendarResponse,
    FomcMinutesResponse,
    FomcStatementResponse,
    extract_meeting_date,
)

# ---------------- calendar discovery ----------------

CAL_HTML = """
<a href="/newsevents/pressreleases/monetary20260429a.htm">HTML</a>
<a href="/monetarypolicy/fomcminutes20260429.htm">HTML</a>
<a href="/monetarypolicy/files/fomcminutes20260429.pdf">PDF</a>
<a href="/monetarypolicy/fomcminutes20260617.htm">HTML</a>
<a href="/newsevents/pressreleases/monetary20260617a.htm">HTML</a>
<a href="/monetarypolicy/fomcminutes20260617.htm">HTML</a>
"""


def test_calendar_discovers_minutes_newest_first_ignoring_pdf() -> None:
    cal = FomcCalendarResponse.from_response(CAL_HTML)
    assert cal.minutes_paths == [
        "/monetarypolicy/fomcminutes20260617.htm",
        "/monetarypolicy/fomcminutes20260429.htm",
    ]
    assert cal.latest_minutes() == "/monetarypolicy/fomcminutes20260617.htm"
    assert cal.prior_minutes() == "/monetarypolicy/fomcminutes20260429.htm"
    # Statement discovery unchanged by the minutes addition.
    assert cal.latest() == "/newsevents/pressreleases/monetary20260617a.htm"


def test_extract_meeting_date_handles_both_path_shapes() -> None:
    assert extract_meeting_date("/newsevents/pressreleases/monetary20260429a.htm") == "2026-04-29"
    assert extract_meeting_date("/monetarypolicy/fomcminutes20260617.htm") == "2026-06-17"
    assert extract_meeting_date("/monetarypolicy/other.htm") == "?"


# ---------------- minutes section splitter ----------------

MINUTES_HTML = """
<html><body>
<div class="nav"><p><strong>Monetary Policy</strong></p></div>
<div id="article" class="col-xs-12">
<h3>Minutes of the Federal Open Market Committee</h3>
<p><strong>June 16</strong><strong>&ndash;17, 2026</strong></p>
<p>A joint meeting of the Federal Open Market Committee and the Board of
Governors was held on Tuesday.</p>
<p><strong>Staff Economic Outlook</strong><br />
The staff forecast was revised up slightly.</p>
<p><strong>Participants' Views on Current Conditions and the Economic Outlook</strong><br />
Almost all participants submitted projections. Several judged risks as elevated.</p>
<p><strong>Committee Policy Actions</strong><br />
The Committee decided to maintain the target range.</p>
<blockquote><p>Directive text.</p></blockquote>
<p><strong>Voting for this action</strong><strong>: </strong>Kevin Warsh and others.</p>
<p><strong>Voting against this action: </strong><strong>None</strong><strong>.</strong></p>
<p><strong>Attendance</strong><br />
Kevin Warsh, Chairman<br />
Someone Else, Vice Chair</p>
</div>
<div class="footer">Last Update: July 08, 2026</div>
</body></html>
"""


def test_minutes_split_into_named_sections() -> None:
    mins = FomcMinutesResponse.from_response(MINUTES_HTML)
    assert mins.section_names() == [
        "Preamble",
        "Staff Economic Outlook",
        "Participants' Views on Current Conditions and the Economic Outlook",
        "Committee Policy Actions",
        "Attendance",
    ]


def test_minutes_preamble_holds_title_and_site_chrome_is_dropped() -> None:
    mins = FomcMinutesResponse.from_response(MINUTES_HTML)
    preamble = dict(mins.sections)["Preamble"]
    assert "Minutes of the Federal Open Market Committee" in preamble
    assert "A joint meeting" in preamble
    # The bolded nav item before the article div must not become a section.
    assert "Monetary Policy" not in mins.section_names()


def test_minutes_vote_tallies_stay_inside_policy_actions() -> None:
    """Inline bold runs ('<strong>Voting for…</strong><strong>: </strong>Name')
    are body text, not section headings."""
    mins = FomcMinutesResponse.from_response(MINUTES_HTML)
    body = dict(mins.sections)["Committee Policy Actions"]
    assert "Voting for this action" in body
    assert "Kevin Warsh and others." in body
    assert "Voting against this action" in body


def test_minutes_footer_trimmed() -> None:
    mins = FomcMinutesResponse.from_response(MINUTES_HTML)
    attendance = dict(mins.sections)["Attendance"]
    assert "Someone Else, Vice Chair" in attendance
    assert "Last Update" not in mins.to_output()


def test_minutes_section_fuzzy_lookup() -> None:
    mins = FomcMinutesResponse.from_response(MINUTES_HTML)
    hit = mins.section("participants")
    assert hit is not None
    assert hit[0].startswith("Participants' Views")
    assert "Several judged risks as elevated." in hit[1]
    assert mins.section("no such section") is None


def test_minutes_empty_html() -> None:
    assert FomcMinutesResponse.from_response("").sections == []
    assert FomcMinutesResponse.from_response("").to_output() == "(no content)"


# ---------------- statement regression after _html_to_text refactor ----------


def test_statement_still_trims_release_body() -> None:
    html = (
        "<html><body><p>chrome</p><p>For release at 2:00 p.m. EDT</p>"
        "<p>Recent indicators suggest growth moderated.</p>"
        "<p>Last Update: June 17, 2026</p></body></html>"
    )
    stmt = FomcStatementResponse.from_response(html)
    assert stmt.text.startswith("For release at")
    assert "growth moderated" in stmt.text
    assert "Last Update" not in stmt.text
