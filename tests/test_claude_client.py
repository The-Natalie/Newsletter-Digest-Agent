from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import StoryRecord
from ai.claude_client import (
    _FILTER_BATCH_SIZE,
    _FILTER_TOOL_NAME,
    _FILTER_TOOL_SCHEMA,
    _FILTER_MAX_BODY_CHARS,
    _build_filter_message,
    _NOISE_BATCH_SIZE,
    _NOISE_TOOL_NAME,
    _NOISE_TOOL_SCHEMA,
    _NOISE_MAX_BODY_CHARS,
    _build_noise_message,
    _REFINE_BATCH_SIZE,
    _REFINE_TOOL_NAME,
    _REFINE_TOOL_SCHEMA,
    _build_refine_message,
)


def _record(body: str, title: str | None = None, newsletter: str = "Test Newsletter") -> StoryRecord:
    return StoryRecord(title=title, body=body, links=[], newsletter=newsletter, date="2026-04-07")


# ── filter_stories constants ──────────────────────────────────────────────────

def test_filter_batch_size():
    """_FILTER_BATCH_SIZE is 25."""
    assert _FILTER_BATCH_SIZE == 25


def test_filter_tool_name():
    """_FILTER_TOOL_NAME matches schema name."""
    assert _FILTER_TOOL_SCHEMA["name"] == _FILTER_TOOL_NAME


def test_filter_schema_decisions_array():
    """Filter tool schema has decisions array with keep and confidence fields."""
    items = _FILTER_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    assert "keep" in items["properties"]
    assert "confidence" in items["properties"]
    assert items["properties"]["confidence"]["enum"] == ["high", "borderline"]


def test_filter_batch_split_75_stories():
    """75 stories split into ceil(75/25) = 3 batches: 25, 25, 25."""
    stories = list(range(75))
    batches = [stories[i:i + _FILTER_BATCH_SIZE] for i in range(0, len(stories), _FILTER_BATCH_SIZE)]
    assert len(batches) == 3
    assert all(len(b) == 25 for b in batches)


def test_filter_batch_split_26_stories():
    """26 stories split into 2 batches: 25, 1."""
    stories = list(range(26))
    batches = [stories[i:i + _FILTER_BATCH_SIZE] for i in range(0, len(stories), _FILTER_BATCH_SIZE)]
    assert len(batches) == 2
    assert len(batches[0]) == 25
    assert len(batches[1]) == 1


def test_filter_message_includes_newsletter_name():
    """Filter message includes the newsletter name for each story."""
    story = _record("OpenAI released a new model.", newsletter="TLDR AI")
    msg = _build_filter_message([story], "AI")
    assert "TLDR AI" in msg


def test_filter_message_includes_title_when_present():
    """Filter message includes the story title when it exists."""
    story = _record("Body text.", title="OpenAI Releases GPT-5")
    msg = _build_filter_message([story], "AI")
    assert "OpenAI Releases GPT-5" in msg


def test_filter_message_includes_body_excerpt():
    """Filter message includes body text (up to _FILTER_MAX_BODY_CHARS)."""
    story = _record("This is the body content of the story.")
    msg = _build_filter_message([story], "AI")
    assert "This is the body content" in msg


def test_filter_message_truncates_long_body():
    """Filter message truncates body to _FILTER_MAX_BODY_CHARS."""
    long_body = "X" * (_FILTER_MAX_BODY_CHARS + 100)
    story = _record(long_body)
    msg = _build_filter_message([story], "AI")
    # The long body should be truncated — not the full body present
    assert "X" * (_FILTER_MAX_BODY_CHARS + 100) not in msg


# ── filter_noise constants ─────────────────────────────────────────────────────

def test_noise_batch_size():
    """_NOISE_BATCH_SIZE is 30."""
    assert _NOISE_BATCH_SIZE == 30


def test_noise_tool_name():
    """_NOISE_TOOL_NAME matches schema name."""
    assert _NOISE_TOOL_SCHEMA["name"] == _NOISE_TOOL_NAME


def test_noise_schema_is_noise_field():
    """Noise tool schema has decisions array with is_noise boolean field."""
    items = _NOISE_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    assert "is_noise" in items["properties"]
    assert items["properties"]["is_noise"]["type"] == "boolean"


def test_noise_batch_split_95_stories():
    """95 stories split into ceil(95/30) = 4 batches: 30, 30, 30, 5."""
    stories = list(range(95))
    batches = [stories[i:i + _NOISE_BATCH_SIZE] for i in range(0, len(stories), _NOISE_BATCH_SIZE)]
    assert len(batches) == 4
    assert len(batches[0]) == 30
    assert len(batches[1]) == 30
    assert len(batches[2]) == 30
    assert len(batches[3]) == 5


def test_noise_message_includes_newsletter_name():
    """Noise message includes the newsletter name for each item."""
    story = _record("This is an article about OpenAI.", newsletter="TLDR AI")
    msg = _build_noise_message([story])
    assert "TLDR AI" in msg


def test_noise_message_includes_body_excerpt():
    """Noise message includes body text."""
    story = _record("This is the body content of a real article.")
    msg = _build_noise_message([story])
    assert "This is the body content" in msg


def test_noise_message_truncates_long_body():
    """Noise message truncates body to _NOISE_MAX_BODY_CHARS."""
    long_body = "X" * (_NOISE_MAX_BODY_CHARS + 100)
    story = _record(long_body)
    msg = _build_noise_message([story])
    assert "X" * (_NOISE_MAX_BODY_CHARS + 100) not in msg


# ── refine_clusters constants ──────────────────────────────────────────────────

def test_refine_batch_size():
    """_REFINE_BATCH_SIZE is 20."""
    assert _REFINE_BATCH_SIZE == 20


def test_refine_tool_name():
    """_REFINE_TOOL_NAME matches schema name."""
    assert _REFINE_TOOL_SCHEMA["name"] == _REFINE_TOOL_NAME


def test_refine_schema_relationship_enum():
    """Refine tool schema has decisions array with relationship string field."""
    items = _REFINE_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    assert "relationship" in items["properties"]
    assert items["properties"]["relationship"]["type"] == "string"


def test_refine_relationship_enum_values():
    """Relationship enum contains exactly the three required values."""
    items = _REFINE_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    enum_values = items["properties"]["relationship"]["enum"]
    assert set(enum_values) == {"same_story", "related_but_distinct", "different"}


def test_refine_message_labels_newsletter():
    """Refine message labels each story with its newsletter name."""
    r1 = _record("OpenAI released GPT-5.", newsletter="TLDR")
    r2 = _record("OpenAI unveiled GPT-5 this week.", newsletter="The Deep View")
    msg = _build_refine_message([(r1, r2)])
    assert "TLDR" in msg
    assert "The Deep View" in msg


def test_refine_batch_split_45_pairs():
    """45 pairs split into ceil(45/20) = 3 batches: 20, 20, 5."""
    pairs = list(range(45))
    batches = [pairs[i:i + _REFINE_BATCH_SIZE] for i in range(0, len(pairs), _REFINE_BATCH_SIZE)]
    assert len(batches) == 3
    assert len(batches[0]) == 20
    assert len(batches[1]) == 20
    assert len(batches[2]) == 5
