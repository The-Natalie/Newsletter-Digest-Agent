from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ingestion.email_parser import (
    _extract_sections,
    _extract_title,
    _select_link,
    _split_list_section,
    parse_emails,
    StoryRecord,
)


# ---------------------------------------------------------------------------
# Helper: minimal HTML wrappers so _extract_sections receives valid HTML
# ---------------------------------------------------------------------------

def _html(body: str) -> str:
    """Wrap body text in minimal HTML structure."""
    return f"<html><body>{body}</body></html>"


def _ul(*items: str) -> str:
    """Build a simple <ul> with each string as a list item."""
    lis = "".join(f"<li>{item}</li>" for item in items)
    return f"<ul>{lis}</ul>"


# ---------------------------------------------------------------------------
# _split_list_section unit tests
# ---------------------------------------------------------------------------

def test_split_list_two_items_with_links():
    """Two bullet items each with a distinct link → splits into 2 sub-sections."""
    sec = (
        "* [Product A](https://example.com/product-a): Description of product A.\n"
        "* [Product B](https://example.com/product-b): Description of product B."
    )
    result = _split_list_section(sec)
    assert result is not None
    assert len(result) == 2
    urls = [r["links"][0]["url"] for r in result]
    assert "https://example.com/product-a" in urls
    assert "https://example.com/product-b" in urls


def test_split_list_five_items_with_links():
    """Five bullet items (like Deep View product updates) → splits into 5 sub-sections."""
    sec = (
        "  * [Manus](https://example.com/manus): Meta's general AI agent launched My Computer, "
        "allowing it to run on your local machine.\n"
        "  * [Perplexity Computer](https://example.com/perplexity): The agentic platform has "
        "now rolled out to all Android users.\n"
        "  * [Kling AI](https://example.com/kling): The AI video-generating platform made its "
        "Team Plan available on the desktop app and web.\n"
        "  * [LTX Studio](https://example.com/ltx): The AI creative suite now supports "
        "translation in 175 languages with realistic lip sync.\n"
        "  * [Claude](https://example.com/claude): Anthropic is doubling usage outside peak "
        "hours for all users for the next two weeks as a thank-you.\n"
    )
    result = _split_list_section(sec)
    assert result is not None
    assert len(result) == 5
    anchors = [r["links"][0]["anchor_text"] for r in result]
    assert "Manus" in anchors
    assert "Perplexity Computer" in anchors
    assert "Claude" in anchors


def test_split_list_preserves_link_per_item():
    """Each returned sub-section's link must match its own item, not a neighbor's."""
    sec = (
        "* [JP Morgan Chase](https://example.com/jp-morgan): Product Manager, Data and AI\n"
        "* [Handshake](https://example.com/handshake): LMMS Specialist - AI Trainer\n"
    )
    result = _split_list_section(sec)
    assert result is not None
    by_anchor = {r["links"][0]["anchor_text"]: r["links"][0]["url"] for r in result}
    assert by_anchor["JP Morgan Chase"] == "https://example.com/jp-morgan"
    assert by_anchor["Handshake"] == "https://example.com/handshake"


def test_split_list_single_item_returns_none():
    """A section with only one list item is not split."""
    sec = "* [Only Story](https://example.com/story): The one story here.\n"
    result = _split_list_section(sec)
    assert result is None


def test_split_list_no_links_returns_none():
    """List items without links are not eligible for splitting."""
    sec = (
        "* Item A without a link\n"
        "* Item B also without a link\n"
    )
    result = _split_list_section(sec)
    assert result is None


def test_split_list_fewer_than_two_linked_items_returns_none():
    """Only one item has a link — not enough to split."""
    sec = (
        "* [Story A](https://example.com/story-a): Has a link.\n"
        "* Item B without a link\n"
    )
    result = _split_list_section(sec)
    assert result is None


def test_split_list_not_triggered_for_paragraph():
    """A plain paragraph section (no list items) is not split."""
    sec = "This is a paragraph about an AI story. It has some detail here."
    result = _split_list_section(sec)
    assert result is None


# ---------------------------------------------------------------------------
# _extract_sections integration tests
# ---------------------------------------------------------------------------

def test_extract_sections_splits_multi_item_list():
    """HTML list with 3 items each linking to a distinct URL → 3 separate sections."""
    html = _html(_ul(
        '<a href="https://example.com/story-a">Story A</a>: First item about topic A.',
        '<a href="https://example.com/story-b">Story B</a>: Second item about topic B.',
        '<a href="https://example.com/story-c">Story C</a>: Third item about topic C.',
    ))
    sections = _extract_sections(html)
    urls = [s["links"][0]["url"] for s in sections if s.get("links")]
    assert "https://example.com/story-a" in urls
    assert "https://example.com/story-b" in urls
    assert "https://example.com/story-c" in urls
    # Story A's section must not contain story B's link
    for s in sections:
        if s.get("links") and s["links"][0]["url"] == "https://example.com/story-a":
            assert all(
                lnk["url"] != "https://example.com/story-b" for lnk in s["links"]
            ), "Story A section must not contain Story B's link"


def test_extract_sections_story_link_not_contaminated_by_neighbour():
    """Core regression: 'Claude' item in a product-updates list must not end up with
    'Perplexity Computer' as its source link."""
    html = _html(_ul(
        '<a href="https://example.com/perplexity-computer">Perplexity Computer</a>: Agentic platform rolled out to Android.',
        '<a href="https://example.com/claude">Claude</a>: Anthropic is doubling usage outside peak hours.',
    ))
    sections = _extract_sections(html)
    claude_section = next(
        (s for s in sections if s.get("links") and "claude" in s["links"][0]["url"]),
        None,
    )
    assert claude_section is not None, "Claude item should produce its own section"
    # Verify Perplexity Computer's link is NOT in Claude's section
    for lnk in claude_section["links"]:
        assert "perplexity" not in lnk["url"], (
            f"Claude section must not carry Perplexity Computer's link; got {lnk['url']}"
        )


def test_extract_sections_single_story_sponsor_unaffected():
    """A sponsor section with a single story and one link is NOT split."""
    html = _html(
        "<p><strong>Sponsor: Acme AI</strong></p>"
        "<p>Acme AI is the enterprise platform for AI deployment. "
        "It offers no-code tools and enterprise security in one hub. "
        '<a href="https://acme.ai/report">Download the 2026 AI Report</a>.</p>'
    )
    sections = _extract_sections(html)
    sponsor_sections = [s for s in sections if "acme" in s.get("text", "").lower()]
    # The sponsor section should still exist (not dropped)
    assert len(sponsor_sections) >= 1
    # It should have the correct link
    all_links = [lnk["url"] for s in sponsor_sections for lnk in s.get("links", [])]
    assert any("acme.ai" in url for url in all_links)


def test_extract_sections_regular_paragraph_unaffected():
    """A standard article section (non-list) passes through unchanged."""
    html = _html(
        "<p>Nvidia announced new robotics platforms at GTC. "
        "The company revealed its full-stack approach. "
        '<a href="https://techcrunch.com/nvidia-gtc">Read the full story</a>. '
        "Physical AI has arrived.</p>"
    )
    sections = _extract_sections(html)
    nvidia_sections = [s for s in sections if "nvidia" in s.get("text", "").lower()]
    assert len(nvidia_sections) >= 1
    assert any(
        "techcrunch.com" in lnk["url"]
        for s in nvidia_sections
        for lnk in s.get("links", [])
    )


# ---------------------------------------------------------------------------
# _extract_title unit tests
# ---------------------------------------------------------------------------

def test_extract_title_heading_line():
    """First # heading becomes title; body excludes that line."""
    title, body = _extract_title("# My Headline\nBody text here.")
    assert title == "My Headline"
    assert "My Headline" not in body
    assert "Body text here." in body


def test_extract_title_h2_heading():
    """## heading is also recognised as title."""
    title, body = _extract_title("## Deep Learning Advances\nSome content follows.")
    assert title == "Deep Learning Advances"
    assert body == "Some content follows."


def test_extract_title_no_heading():
    """Section with no # heading returns title=None and unchanged text."""
    text = "OpenAI released a new model this week with improved reasoning."
    title, body = _extract_title(text)
    assert title is None
    assert body == text


def test_extract_title_empty_heading():
    """A heading line with only # markers and no text returns title=None."""
    title, body = _extract_title("# \nBody content here.")
    assert title is None


def test_extract_title_leading_blank_lines_skipped():
    """Leading blank lines before the heading are skipped."""
    title, body = _extract_title("\n\n# Heading\nBody.")
    assert title == "Heading"
    assert body == "Body."


# ---------------------------------------------------------------------------
# _select_link unit tests
# ---------------------------------------------------------------------------

def test_select_link_returns_first_url():
    """Returns the url of the first link in the list."""
    links = [
        {"url": "https://example.com/story", "anchor_text": "Story"},
        {"url": "https://example.com/other", "anchor_text": "Other"},
    ]
    assert _select_link(links) == "https://example.com/story"


def test_select_link_empty_returns_none():
    """Empty links list returns None."""
    assert _select_link([]) is None


# ---------------------------------------------------------------------------
# parse_emails() — StoryRecord output shape tests
# ---------------------------------------------------------------------------

def _make_raw_email(
    html_body: str,
    sender: str = "Test Newsletter <test@example.com>",
    date: str = "Mon, 14 Mar 2026 10:00:00 +0000",
) -> bytes:
    """Build a minimal raw MIME email with an HTML body for parse_emails() tests."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["Subject"] = "Test Issue"
    msg["Date"] = date
    msg.attach(MIMEText(html_body, "html"))
    return msg.as_bytes()


def test_parse_emails_returns_story_records():
    """parse_emails() returns a list of StoryRecord instances."""
    html = _html("<p>Google released a new AI model with improved reasoning capabilities this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert isinstance(records, list)
    assert all(isinstance(r, StoryRecord) for r in records)


def test_parse_emails_newsletter_field():
    """StoryRecord.newsletter is set from the From display name."""
    html = _html("<p>OpenAI announced a new API update with lower pricing for GPT-4o.</p>")
    raw = _make_raw_email(html, sender="TLDR AI <tldr@example.com>")
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].newsletter == "TLDR AI"


def test_parse_emails_date_field_format():
    """StoryRecord.date is formatted as YYYY-MM-DD."""
    html = _html("<p>Anthropic released Claude 3.7 Sonnet with extended thinking capability.</p>")
    raw = _make_raw_email(html, date="Fri, 14 Mar 2026 10:00:00 +0000")
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].date == "2026-03-14"


def test_parse_emails_title_extracted_from_heading():
    """StoryRecord.title is extracted from a markdown heading; body excludes the heading line."""
    html = _html(
        "<h2>New AI chip breaks benchmark records</h2>"
        "<p>Nvidia unveiled a new data-center GPU at GTC 2026 that outperforms the H100 on "
        "all major inference benchmarks by more than 40 percent.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    r = records[0]
    assert r.title == "New AI chip breaks benchmark records"
    assert "New AI chip breaks benchmark records" not in r.body


def test_parse_emails_title_none_when_no_heading():
    """StoryRecord.title is None when the section has no markdown heading."""
    html = _html(
        "<p>Google DeepMind published benchmark results showing new SOTA performance.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].title is None


def test_parse_emails_link_extracted():
    """StoryRecord.link is the first content URL from the section."""
    html = _html(
        '<p>OpenAI cut API prices. <a href="https://openai.com/pricing">See pricing</a>.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].link == "https://openai.com/pricing"


def test_parse_emails_link_none_when_no_link():
    """StoryRecord.link is None when the section contains no content URLs."""
    html = _html("<p>AI safety researchers published a new alignment paper this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].link is None


def test_parse_emails_short_item_preserved():
    """A one-sentence story item under 100 chars is NOT dropped (short items are valid)."""
    html = _html(
        '<p>GPT-5 is live. <a href="https://openai.com/gpt-5">Details here.</a></p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1


def test_parse_emails_empty_email_skipped():
    """An email with no body parts produces no story records."""
    msg = MIMEMultipart("alternative")
    msg["From"] = "Newsletter <test@example.com>"
    msg["Subject"] = "Empty"
    msg["Date"] = "Mon, 14 Mar 2026 10:00:00 +0000"
    records = parse_emails([msg.as_bytes()])
    assert records == []


def test_parse_emails_multiple_emails_flat_list():
    """Two emails each producing one section → flat list with records from both."""
    html1 = _html("<p>Google launched a new search AI feature with visual understanding.</p>")
    html2 = _html("<p>Meta released an open-weights model with strong benchmark results.</p>")
    raw1 = _make_raw_email(html1, sender="Newsletter A <a@example.com>")
    raw2 = _make_raw_email(html2, sender="Newsletter B <b@example.com>")
    records = parse_emails([raw1, raw2])
    newsletters = [r.newsletter for r in records]
    assert "Newsletter A" in newsletters
    assert "Newsletter B" in newsletters


# ---------------------------------------------------------------------------
# Phase 2: Extraction quality filter tests
# ---------------------------------------------------------------------------

def test_table_artifact_dropped():
    """A section consisting mainly of pipe characters is dropped as a table artifact."""
    from ingestion.email_parser import _is_table_artifact
    assert _is_table_artifact("| | | |  March 17, 2026  | Read online")
    assert not _is_table_artifact("Nvidia announced new robotics platforms at GTC 2026.")


def test_empty_anchor_link_stripped_from_body():
    """An image link [](url) does not appear as raw syntax in StoryRecord.body."""
    html = _html(
        '<img src="https://example.com/img.png" alt="">'  # becomes [](url) in markdown
        '<p>OpenAI cut API prices for all GPT-4o users starting this month.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    for r in records:
        assert "[](https://" not in r.body, (
            f"Raw empty-anchor link syntax found in body: {r.body[:100]}"
        )


def test_toc_section_dropped():
    """A numbered list of headline links with no prose is dropped as a ToC section."""
    html = _html(
        "<ol>"
        "<li><a href='https://example.com/story-1'>GPT-5 launches with multimodal reasoning</a></li>"
        "<li><a href='https://example.com/story-2'>Nvidia unveils Blackwell Ultra GPU chip</a></li>"
        "<li><a href='https://example.com/story-3'>Meta releases Llama 4 open weights model</a></li>"
        "</ol>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # The ToC section (3 links, no prose) should not produce records
    # Any record that IS produced must have meaningful prose beyond just headline text
    for r in records:
        prose_words = len(r.body.split())
        assert prose_words >= 6, (
            f"ToC-like section produced a sparse record ({prose_words} words): {r.body[:100]}"
        )


def test_story_with_multiple_inline_links_not_dropped():
    """A story section with 3+ inline links and substantial prose is NOT dropped as a ToC."""
    html = _html(
        "<p>Nvidia announced the <a href='https://nvidia.com/blackwell'>Blackwell Ultra</a> GPU at GTC. "
        "The new chip offers <a href='https://nvidia.com/perf'>40% better inference performance</a> than H100. "
        "It will be available from <a href='https://nvidia.com/partners'>certified partners</a> in Q3 2026.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1, "Story section with multiple inline links must not be dropped"
    assert any("Nvidia" in r.body or "Blackwell" in r.body for r in records)


def test_intro_signal_section_dropped():
    """A section containing 'in today's issue' with no story content is dropped."""
    html = _html(
        "<p>In today's issue: AI funding, chip announcements, and open-source releases.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    intro_records = [r for r in records if "in today" in r.body.lower()]
    assert intro_records == [], (
        f"Intro section produced {len(intro_records)} record(s): {[r.body[:80] for r in intro_records]}"
    )


def test_short_valid_story_still_preserved_after_phase2():
    """Phase 2 filters do not drop short valid story items."""
    html = _html(
        '<p>GPT-5 is live. <a href="https://openai.com/gpt-5">Details here.</a></p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1, "Short valid story must not be dropped by Phase 2 filters"
