from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import _extract_sections, _split_list_section


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
