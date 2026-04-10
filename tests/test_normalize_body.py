from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.digest_builder import _normalize_body, _normalize_title


def test_bold_markers_removed():
    assert _normalize_body("This is **bold** text") == "This is bold text"


def test_bold_underscore_markers_removed():
    assert _normalize_body("This is __bold__ text") == "This is bold text"


def test_italic_markers_removed():
    assert _normalize_body("This is *italic* text") == "This is italic text"


def test_italic_underscore_markers_removed():
    assert _normalize_body("This is _italic_ text") == "This is italic text"


def test_heading_markers_removed():
    assert _normalize_body("## Section Title") == "Section Title"


def test_heading_multiple_levels_removed():
    assert _normalize_body("### Deep heading") == "Deep heading"


def test_stray_double_asterisks_removed():
    # ** is removed; the resulting extra space is then collapsed to one
    assert _normalize_body("text ** more text") == "text more text"


def test_line_start_bullet_preserved():
    """* at line start is kept — it's a valid bullet marker for marked.js."""
    assert _normalize_body("* list item") == "* list item"


def test_inline_bullet_converted_to_newline():
    """Inline ' * item' separators are split onto their own lines."""
    result = _normalize_body("You can: * item one * item two * item three")
    assert result == "You can:\n* item one\n* item two\n* item three"


def test_inline_bullet_multiword_items():
    """Each inline bullet item is placed on its own line."""
    text = "Features: * Run free inference * Launch GPU instances * Deploy with one click"
    result = _normalize_body(text)
    lines = result.splitlines()
    assert lines[0] == "Features:"
    assert any("Run free inference" in l for l in lines)
    assert any("Launch GPU instances" in l for l in lines)
    assert any("Deploy with one click" in l for l in lines)


# ---------------------------------------------------------------------------
# _normalize_title tests
# ---------------------------------------------------------------------------

def test_title_bold_markers_removed():
    assert _normalize_title("**Tuesday Tool Tip:**") == "Tuesday Tool Tip:"


def test_title_leading_block_symbol_removed():
    assert _normalize_title("■Tuesday Tool Tip") == "Tuesday Tool Tip"


def test_title_block_symbol_then_bold_removed():
    """■**Title** → Title (block char + bold both stripped)."""
    result = _normalize_title("■**Tuesday Tool Tip:**")
    assert result == "Tuesday Tool Tip:"


def test_title_stray_asterisks_removed():
    assert _normalize_title("n**Tuesday Tool Tip:**") == "nTuesday Tool Tip:"


def test_title_none_returns_none():
    assert _normalize_title(None) is None


def test_title_empty_string_returns_none():
    assert _normalize_title("") is None


def test_title_plain_text_unchanged():
    assert _normalize_title("OpenAI releases new model") == "OpenAI releases new model"


def test_title_whitespace_normalized():
    assert _normalize_title("Title  with   spaces") == "Title with spaces"


def test_table_separator_line_removed():
    result = _normalize_body("header\n---|---\ncontent")
    assert "---|---" not in result
    assert "content" in result


def test_block_symbol_removed():
    assert "■" not in _normalize_body("■ item text")


def test_filled_square_removed():
    assert "▪" not in _normalize_body("▪ item text")


def test_underscore_in_url_preserved():
    """Underscores inside URLs must not be stripped."""
    text = "See https://example.com/some_page_here for details"
    assert "some_page_here" in _normalize_body(text)


def test_snake_case_preserved():
    """Underscores inside identifiers must not be stripped."""
    text = "The function is called do_something_useful"
    assert "do_something_useful" in _normalize_body(text)


def test_real_content_preserved():
    """Normalization must not remove real words."""
    text = "OpenAI released a new model this week with improved reasoning."
    assert _normalize_body(text) == text


def test_malformed_emphasis_cleaned():
    """Mixed/malformed markers like **_text_** are cleaned."""
    result = _normalize_body("**_bold-italic_**")
    assert "**" not in result
    assert "_" not in result


def test_dot_underscore_dot_cleaned():
    """._. artifact pattern is cleaned."""
    result = _normalize_body("sentence._. continuation")
    assert "_" not in result


def test_multiline_body():
    text = "## Intro\n\n**Key point:** this matters.\n\n- item one\n- item two"
    result = _normalize_body(text)
    assert "##" not in result
    assert "**" not in result
    assert result.startswith("Intro")


def test_excess_blank_lines_collapsed():
    text = "line one\n\n\n\nline two"
    result = _normalize_body(text)
    assert "\n\n\n" not in result


def test_excess_spaces_collapsed():
    text = "word1   word2"
    assert _normalize_body(text) == "word1 word2"


def test_empty_string_returns_empty():
    assert _normalize_body("") == ""


def test_plain_text_unchanged():
    text = "This is a plain sentence with no formatting."
    assert _normalize_body(text) == text
