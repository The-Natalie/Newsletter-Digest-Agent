from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ingestion.email_parser import (
    _collect_links,
    _extract_sections,
    _extract_title,
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
# _collect_links unit tests
# ---------------------------------------------------------------------------

def test_collect_links_returns_all_urls():
    """_collect_links() returns all URLs from the links list."""
    links = [
        {"url": "https://example.com/a", "anchor_text": "First"},
        {"url": "https://example.com/b", "anchor_text": "Second"},
    ]
    assert _collect_links(links) == ["https://example.com/a", "https://example.com/b"]


def test_collect_links_empty_returns_empty_list():
    """_collect_links() returns empty list when no links."""
    assert _collect_links([]) == []


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
    """StoryRecord.links contains the content URL from the section."""
    html = _html(
        '<p>OpenAI cut API prices. <a href="https://openai.com/pricing">See pricing</a>.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert "https://openai.com/pricing" in records[0].links


def test_parse_emails_link_none_when_no_link():
    """StoryRecord.links is empty list when the section contains no content URLs."""
    html = _html("<p>AI safety researchers published a new alignment paper this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].links == []


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


# ---------------------------------------------------------------------------
# Phase 3: Post-title body artifact filter tests
# ---------------------------------------------------------------------------

def test_heading_with_pipe_body_not_a_story():
    """_is_table_artifact catches body='|' that remains after _extract_title strips a heading.

    This is the exact failure mode observed in real email parsing: a section heading
    is a genuine article title, but the adjacent content (a table cell fragment) becomes
    the body after title extraction. The resulting record has body='|' and no story content.
    """
    from ingestion.email_parser import _extract_title, _is_table_artifact
    section_text = "# Nvidia builds the tech stack for the robotics era\n|"
    title, body = _extract_title(section_text)
    assert title == "Nvidia builds the tech stack for the robotics era"
    assert _is_table_artifact(body), (
        f"body={body!r} after title extraction should be a table artifact"
    )


def test_titled_section_with_pipe_body_dropped_by_parse_emails():
    """parse_emails() drops a record when title extraction leaves a pipe-only body."""
    html = _html(
        "<h3>Nvidia builds the tech stack for the robotics era</h3>"
        "<p>|</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    pipe_body_records = [r for r in records if r.body.strip() == "|"]
    assert pipe_body_records == [], (
        f"Got {len(pipe_body_records)} record(s) with body='|': "
        f"{[r.title for r in pipe_body_records]}"
    )


# ---------------------------------------------------------------------------
# Phase 4: Story reassembly, pipe stripping, bold-title detection, xa0 tests
# ---------------------------------------------------------------------------

def test_trailing_pipe_stripped_from_body():
    """Body text with trailing '|' has the pipe stripped."""
    html = _html(
        "<p>Nvidia is betting on robots, without actually building any robots.</p>"
        "<p>|</p>"   # trailing table artifact — same paragraph structure as real email
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    for r in records:
        assert not r.body.rstrip().endswith("|"), (
            f"Trailing '|' found in body: {r.body[-50:]!r}"
        )


def test_xa0_normalized_in_body():
    """Non-breaking spaces are normalized to regular spaces in body text."""
    html = _html(
        "<p>In the AI era, pricing is your product.\xa0 The shift is here.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    for r in records:
        assert '\xa0' not in r.body, f"\\xa0 found in body: {r.body[:100]!r}"


def test_together_with_section_not_dropped():
    """After the philosophy change, 'together with' sections are no longer dropped.
    Sponsor labels are content-adjacent; keep/drop is the LLM filter's job.
    """
    html = (
        "<html><body>"
        "<p>Together with Sponsor Corp. This section used to be dropped but now passes through.</p>"
        "<p>Valid story content appears in a separate section here.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # The sponsor-labeled section must NOT be silently discarded
    bodies = " ".join(r.body for r in results)
    assert "Together with Sponsor Corp" in bodies, (
        "Sponsor-labeled section was dropped by parser — should be passed to LLM filter"
    )


def test_thanks_for_reading_section_not_dropped():
    """After the philosophy change, 'thanks for reading' outro sections are no longer dropped.
    Sign-off content is content-adjacent; keep/drop is the LLM filter's job.
    """
    html = _html(
        "<p>Thanks for reading today's edition of The Deep View! We'll see you in the next one.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    outro_records = [r for r in records if "thanks for reading" in r.body.lower()]
    assert len(outro_records) >= 1, (
        "Outro section was dropped by parser — should be passed to LLM filter"
    )


def test_story_heading_collects_following_paragraphs():
    """A story heading merges with all following paragraphs into one record."""
    html = _html(
        "<h1>Nvidia builds the tech stack for the robotics era</h1>"
        "<p>Nvidia is betting on robots, without actually building any robots.</p>"
        "<p>This is a continuation paragraph with more context about the story.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # All three parts should be in one record
    assert len(records) == 1, f"Expected 1 record, got {len(records)}"
    r = records[0]
    assert r.title == "Nvidia builds the tech stack for the robotics era"
    assert "Nvidia is betting on robots" in r.body
    assert "continuation paragraph" in r.body


def test_category_heading_does_not_merge_following_stories():
    """A bold-wrapped category heading (TLDR-style) does NOT collect following stories."""
    html = _html(
        "<h1><strong>Headlines &amp; Launches</strong></h1>"
        "<p><strong>Meta Acquired Moltbook (3 minute read)</strong> Meta has acquired Moltbook.</p>"
        "<p><strong>Nvidia Invests in Lab (2 minute read)</strong> Nvidia announced an investment.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # Two stories should be two records (category heading does not merge them)
    assert len(records) >= 2, (
        f"Expected 2+ records for two distinct stories, got {len(records)}"
    )


def test_bold_title_extracted_as_story_title():
    """A section starting with **Bold Title** has it extracted as the story title."""
    html = _html(
        "<p><strong>Meta Acquired Moltbook (3 minute read)</strong></p>"
        "<p>Meta has acquired Moltbook, a Reddit-like network where AI agents collaborate.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    titled = [r for r in records if r.title is not None]
    assert titled, "Expected at least one record with a title from bold-title pattern"
    assert any("Meta Acquired Moltbook" in r.title for r in titled), (
        f"Expected title containing 'Meta Acquired Moltbook', got: {[r.title for r in titled]}"
    )


def test_links_field_is_list():
    """StoryRecord.links is always a list (empty list when no links)."""
    html = _html("<p>AI safety researchers published a new alignment paper this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    for r in records:
        assert isinstance(r.links, list), f"links should be a list, got {type(r.links)}"


def test_links_field_contains_story_urls():
    """StoryRecord.links contains all non-boilerplate story URLs."""
    html = _html(
        '<p>OpenAI cut API prices. '
        '<a href="https://openai.com/pricing">See pricing</a> and '
        '<a href="https://openai.com/blog/api-update">read the announcement</a>.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    all_links = [url for r in records for url in r.links]
    assert any("openai.com/pricing" in url for url in all_links)
    assert any("openai.com/blog" in url for url in all_links)


def test_source_count_default_is_1():
    """StoryRecord.source_count defaults to 1 when produced by parse_emails()."""
    html = _html("<p>Anthropic released Claude 4 with improved reasoning capabilities.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    for r in records:
        assert r.source_count == 1, f"Expected source_count=1, got {r.source_count}"


# ---------------------------------------------------------------------------
# Phase 5: body cleanup — regression tests
# ---------------------------------------------------------------------------

def test_boilerplate_unicode_apostrophe_dropped():
    """Section with U+2019 smart apostrophe in 'TODAY\u2019S NEWSLETTER' is dropped as boilerplate."""
    html = (
        "<html><body>"
        "<p><strong>Welcome back.</strong> IN TODAY\u2019S NEWSLETTER</p>"
        "<p>Real story content here that is long enough to pass filters and be kept.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # The intro/ToC section must be dropped; no record should carry the newsletter marker
    assert all(
        "today\u2019s newsletter" not in (r.body or "").lower()
        and "in today's newsletter" not in (r.body or "").lower()
        for r in results
    )


def test_bold_artifact_stripped_from_body():
    """'****' empty-bold artifacts from html2text are removed from body text."""
    html = (
        "<html><body>"
        "<h1>Story headline</h1>"
        "<p>First paragraph with <strong></strong> trailing artifact.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert '****' not in results[0].body


def test_theme_label_not_absorbed_into_story_body():
    """Short structural labels like '| HARDWARE' are not absorbed into the preceding story body."""
    html = (
        "<html><body>"
        "<h1>Main story headline</h1>"
        "<p>Main story body text with enough content to pass the length filter and be kept.</p>"
        "<p>| HARDWARE</p>"
        "<h1>Next story headline</h1>"
        "<p>Next story body text.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    # First story body must not contain the theme label
    assert 'HARDWARE' not in results[0].body


def test_empty_anchor_image_link_captured():
    """Article image links rendered as [](url) by html2text are included in the links list."""
    html = (
        "<html><body>"
        "<h1>Story with image link</h1>"
        '<p><a href="https://example.com/article"><img src="https://img.example.com/photo.jpg" /></a></p>'
        "<p>Story body text with enough content to pass all filters and be included.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    # The article URL behind the image must appear in the links list
    assert any("example.com/article" in url for url in results[0].links)


def test_trailing_table_artifact_line_stripped():
    """Trailing '| |  SUBSCRIBE'-style structural cell lines are stripped from body."""
    html = (
        "<html><body>"
        "<p>Valid story content about a podcast that has enough text to pass the length filter.</p>"
        "<p>| |  SUBSCRIBE</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert 'SUBSCRIBE' not in results[0].body
    assert results[0].body.strip()  # body is not empty after stripping


def test_trailing_get_in_touch_line_stripped():
    """Trailing '| |  GET IN TOUCH WITH US HERE' structural cell is stripped from body."""
    html = (
        "<html><body>"
        "<p>If you want to advertise to our audience, please get in touch with us here for details.</p>"
        "<p>| |  GET IN TOUCH WITH US HERE</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert 'GET IN TOUCH WITH US HERE' not in results[0].body


def test_split_list_preserves_link_free_items():
    """A link-free bullet item in a multi-link list is not silently dropped."""
    html = (
        "<html><body><ul>"
        '<li><a href="https://example.com/a">Story A about something interesting and newsworthy</a></li>'
        "<li>Story B has no link but enough text to be a valid item worth preserving here</li>"
        '<li><a href="https://example.com/c">Story C about something else entirely newsworthy</a></li>'
        "</ul></body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    bodies = [r.body for r in results]
    assert any("Story A" in b for b in bodies)
    assert any("Story B" in b for b in bodies), "Link-free list item must not be dropped"
    assert any("Story C" in b for b in bodies)


# ---------------------------------------------------------------------------
# Phase 6: assembly philosophy — regression tests
# ---------------------------------------------------------------------------

def test_sponsor_separated_continuation_assembled():
    """A story continuation separated from its heading by a sponsor section is assembled into one record.

    TDV structure: # Article heading → main body → sponsor content → continuation.
    The inner collection loop must not break at the sponsor section.
    """
    html = (
        "<html><body>"
        "<h1>Main article heading</h1>"
        "<p>First part of the article body with enough content to be valid and pass filters.</p>"
        "<p>Together with Sponsor Corp. This is the sponsor content that was previously causing a break.</p>"
        "<p>This is the analytical continuation that was previously severed into a separate record.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # All three sections should be in ONE record (same heading-led story)
    assert len(results) == 1, f"Expected 1 assembled record, got {len(results)}"
    assert "First part" in results[0].body
    assert "analytical continuation" in results[0].body


def test_trailing_whitespace_stripped_from_body():
    """Body lines must not have trailing whitespace (html2text table-cell artifact)."""
    html = (
        "<html><body>"
        "<p>First sentence of the story body content here.  </p>"
        "<p>Second sentence with trailing spaces.   </p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    for line in results[0].body.split('\n'):
        assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"


def test_nested_bracket_anchor_link_extracted():
    """A markdown link whose anchor text contains nested brackets is correctly extracted.

    Example: ["not ruling them [ads] out"](https://example.com/article)
    The URL must appear in links and must NOT appear as raw markdown in body.
    """
    html = (
        "<html><body>"
        '<p>Google is <a href="https://example.com/gemini">\'not ruling them [ads] out\'</a>'
        " of Gemini, according to Wired.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert any("example.com/gemini" in url for url in results[0].links), (
        "Nested-bracket anchor link URL not extracted into links list"
    )
    assert "](https://" not in results[0].body, (
        "Raw markdown link syntax still present in body"
    )


# ---------------------------------------------------------------------------
# Phase 7: two-line heading detection
# ---------------------------------------------------------------------------

def test_is_story_heading_second_line():
    """_is_story_heading returns True when the # heading is on the second non-empty line."""
    from ingestion.email_parser import _is_story_heading
    assert _is_story_heading("GTC COVERAGE BROUGHT TO YOU BY IREN\n\n# Unleashing NVIDIA Blackwell")
    assert _is_story_heading("Category Label\n# Story Title")
    assert not _is_story_heading("Regular paragraph text\n\nMore paragraph text")
    assert not _is_story_heading("Label\n# **Bold-Wrapped Category**")


def test_extract_title_second_line_heading():
    """_extract_title extracts a # heading from the second non-empty line.

    Pre-heading label text must appear at the start of the body.
    """
    from ingestion.email_parser import _extract_title
    title, body = _extract_title(
        "GTC COVERAGE BROUGHT TO YOU BY IREN\n\n# Unleashing NVIDIA Blackwell\n\nIREN content here."
    )
    assert title == "Unleashing NVIDIA Blackwell"
    assert "GTC COVERAGE BROUGHT TO YOU BY IREN" in body
    assert "IREN content here." in body
    assert "# " not in body, "Raw heading syntax must not appear in body"


def test_category_label_then_heading_splits_into_separate_story():
    """A fused section (category label + # heading) is recognized as a story boundary.

    Simulates the html2text trailing-space artifact where a sponsor label and the
    following heading are fused into one section via '  \\n  \\n' instead of '\\n\\n'.
    The two-line heading check must treat this as a story heading so the inner
    assembly loop breaks at it and a new story starts.
    """
    # Directly call _extract_sections with pre-fused text via the section-level unit tests
    # above (_is_story_heading, _extract_title). End-to-end: verify two stories are produced
    # when label and heading come from separate HTML elements (clean \n\n — label absorbed
    # into preceding story, heading starts new story).
    html = (
        "<html><body>"
        "<h1>First article heading</h1>"
        "<p>First article body content that is long enough to be a valid story record.</p>"
        "<p>GTC COVERAGE BROUGHT TO YOU BY SPONSOR</p>"
        "<h2>Second article title here</h2>"
        "<p>Second article body content that is also long enough to be valid here.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    titles = [r.title for r in results]
    # Two distinct stories must be produced
    assert any("First article heading" in (t or "") for t in titles), "First article title missing"
    assert any("Second article title here" in (t or "") for t in titles), "Second article title missing"
