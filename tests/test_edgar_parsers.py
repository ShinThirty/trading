"""Tests for the pure-function EDGAR section/diff parsers.

Issuer formatting varies enough that the section anchors and risk-factor
splitter need pinned behaviour — these tests exist so a refactor that breaks
real-world filings fails loudly.
"""

from trading_clients.endpoints.edgar import (
    RiskItem,
    diff_risk_factor_items,
    extract_section,
    split_risk_factor_items,
)


# ---------------- extract_section ----------------


def test_extract_section_picks_body_over_toc() -> None:
    """When a section header appears in both TOC and body, the body span
    (longer) should win."""
    text = (
        "Table of Contents\n"
        "Item 1A. Risk Factors\n"
        "Item 1B. Unresolved Staff Comments\n"
        "Item 2. Properties\n"
        "\n\n"
        "Item 1A. Risk Factors\n"
        "We may not be profitable. " * 200 + "\n"
        "Item 1B. Unresolved Staff Comments\n"
        "None.\n"
    )
    out = extract_section(text, "risk_factors")
    assert "We may not be profitable" in out
    assert "Item 1B" not in out


def test_extract_section_handles_multiline_phrase() -> None:
    """The MD&A header sometimes wraps mid-phrase after HTML cleanup."""
    text = (
        "Item 7. Management's Discussion\nand Analysis of Financial Condition\n"
        "We delivered record revenue. " * 100 + "\n"
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk\n"
    )
    out = extract_section(text, "mda")
    assert "record revenue" in out
    assert "Quantitative" not in out


def test_extract_section_returns_empty_when_missing() -> None:
    assert extract_section("nothing here", "risk_factors") == ""


def test_extract_section_caps_at_max_len() -> None:
    cfg_max = 10_000  # segments
    text = "Segment Information\n" + ("X" * 50_000)
    out = extract_section(text, "segments")
    assert len(out) <= cfg_max


def test_extract_section_unknown_id_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unknown section_id"):
        extract_section("foo", "not-a-real-section")


# ---------------- split_risk_factor_items ----------------


def test_split_risk_factor_items_groups_heading_then_body() -> None:
    text = (
        "We depend on a small number of customers\n"
        + ("A significant portion of our revenue comes from a handful of customers. " * 20)
        + "\n"
        + "Our supply chain is concentrated in Asia\n"
        + ("A natural disaster, geopolitical event, or pandemic could disrupt supply. " * 20)
    )
    items = split_risk_factor_items(text)
    assert len(items) == 2
    assert items[0].headline.startswith("We depend on a small number")
    assert "handful of customers" in items[0].body
    assert items[1].headline.startswith("Our supply chain")


def test_split_risk_factor_items_extracts_first_sentence_when_no_heading() -> None:
    long_para = "Cybersecurity incidents could harm our reputation and financial results. " + (
        "More body text. " * 40
    )
    items = split_risk_factor_items(long_para)
    assert len(items) == 1
    assert "Cybersecurity incidents" in items[0].headline
    # Headline should not include the trailing period.
    assert not items[0].headline.endswith(".")


def test_split_risk_factor_items_skips_short_noise() -> None:
    text = (
        "12\n"  # page number
        "PART I\n" + ("Real risk factor body about regulatory exposure. " * 30)
    )
    items = split_risk_factor_items(text)
    # The standalone short lines should not produce items on their own.
    assert len(items) == 1


# ---------------- diff_risk_factor_items ----------------


def _item(headline: str, body: str = "") -> RiskItem:
    # Pad body to ensure tokens land in the diff fingerprint.
    return RiskItem(headline=headline, body=body or (headline + " " * 5) * 5)


def test_diff_detects_added_and_removed() -> None:
    prior = [
        _item("Customer concentration risk in semiconductor manufacturing"),
        _item("Foreign exchange exposure on Japanese yen revenue"),
    ]
    current = [
        _item("Customer concentration risk in semiconductor manufacturing"),
        _item("Cybersecurity attacks on cloud infrastructure"),  # new
    ]
    diff = diff_risk_factor_items(current, prior)
    assert len(diff.added) == 1
    assert "Cybersecurity" in diff.added[0].headline
    assert len(diff.removed) == 1
    assert "yen" in diff.removed[0].headline.lower()


def test_diff_buckets_unchanged_vs_changed_by_threshold() -> None:
    # Same headline, similar body — UNCHANGED.
    prior_a = _item(
        "Supply chain disruption could materially harm operations",
        "natural disaster pandemic geopolitical event factory shutdown shipping delay",
    )
    current_a = _item(
        "Supply chain disruption could materially harm operations",
        "natural disaster pandemic geopolitical event factory shutdown shipping delay",
    )
    # Same topic, very different body — CHANGED.
    prior_b = _item(
        "Regulatory environment is evolving",
        "antitrust investigation Europe inquiry merger review competition authority",
    )
    current_b = _item(
        "Regulatory environment is evolving",
        "data privacy GDPR consent cookie tracking advertising disclosure obligations",
    )
    diff = diff_risk_factor_items([current_a, current_b], [prior_a, prior_b])
    assert diff.unchanged_count == 1
    assert len(diff.changed) == 1
    assert diff.changed[0][0].headline.startswith("Regulatory")


def test_diff_empty_inputs() -> None:
    diff = diff_risk_factor_items([], [])
    assert not diff.has_changes
    assert diff.unchanged_count == 0


def test_diff_all_added_when_prior_empty() -> None:
    current = [_item("First risk"), _item("Second risk")]
    diff = diff_risk_factor_items(current, [])
    assert len(diff.added) == 2
    assert not diff.removed
