from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.embedder import StoryChunk
from processing.deduplicator import _build_sources, _is_cta_link, _score_source, _ANCHOR_IDEAL_MAX_WORDS


def _chunk(sender: str, links: list[dict]) -> StoryChunk:
    return StoryChunk(text="test text", sender=sender, links=links)


def test_single_chunk_single_link():
    """Single chunk with one link — that link is returned."""
    cluster = [_chunk("TLDR AI", [{"url": "https://example.com/story", "anchor_text": "Story Headline"}])]
    result = _build_sources(cluster)
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/story"
    assert result[0]["newsletter"] == "TLDR AI"


def test_single_chunk_picks_best_link():
    """Single chunk with multiple links — best by _score_source is selected."""
    links = [
        {"url": "https://example.com/", "anchor_text": "Home"},
        {"url": "https://example.com/blog/ai-story", "anchor_text": "AI Story Title"},
    ]
    cluster = [_chunk("AI Newsletter", links)]
    result = _build_sources(cluster)
    assert len(result) == 1
    # /blog/ai-story has path_depth=2; example.com/ has depth=0 — deeper wins
    assert result[0]["url"] == "https://example.com/blog/ai-story"


def test_two_chunks_independent_attribution():
    """Two chunks each contribute their own best link — no cross-contamination."""
    story_chunk = _chunk(
        "AI Weekly",
        [{"url": "https://example.com/ai-chip-story", "anchor_text": "New AI chip breaks records"}],
    )
    sponsor_chunk = _chunk(
        "TLDR AI",
        [{"url": "https://tracking.example.com/CL0/sponsor",
          "anchor_text": "Google Cloud x NVIDIA: Engineering the Future of AI (Sponsor)"}],
    )
    result = _build_sources([story_chunk, sponsor_chunk])
    assert len(result) == 2
    by_newsletter = {s["newsletter"]: s["url"] for s in result}
    assert by_newsletter["AI Weekly"] == "https://example.com/ai-chip-story"
    assert by_newsletter["TLDR AI"] == "https://tracking.example.com/CL0/sponsor"


def test_duplicate_url_across_chunks_deduplicated():
    """If two chunks link to the same URL, it appears only once."""
    url = "https://example.com/shared-story"
    chunk_a = _chunk("Newsletter A", [{"url": url, "anchor_text": "Story A"}])
    chunk_b = _chunk("Newsletter B", [{"url": url, "anchor_text": "Story B"}])
    result = _build_sources([chunk_a, chunk_b])
    assert len(result) == 1
    assert result[0]["url"] == url


def test_chunk_with_no_links_skipped():
    """Chunks with no links are skipped; only chunks with links contribute sources."""
    chunk_no_links = _chunk("Newsletter A", [])
    chunk_with_link = _chunk("Newsletter B", [{"url": "https://example.com/story", "anchor_text": "Story"}])
    result = _build_sources([chunk_no_links, chunk_with_link])
    assert len(result) == 1
    assert result[0]["newsletter"] == "Newsletter B"


def test_all_chunks_no_links_returns_empty():
    """Cluster where no chunk has links returns [] (sourceless — will be dropped)."""
    cluster = [_chunk("Newsletter A", []), _chunk("Newsletter B", [])]
    result = _build_sources(cluster)
    assert result == []


def test_empty_cluster_returns_empty():
    """Empty cluster returns []."""
    assert _build_sources([]) == []


def test_sponsor_anchor_does_not_steal_story_link():
    """
    Core regression: sponsor anchor with longer text does not replace story link
    from a different chunk. Per-chunk selection prevents cross-contamination.
    """
    story_chunk = _chunk(
        "The Batch",
        [{"url": "https://deeplearning.ai/the-batch/issue-123", "anchor_text": "New model release"}],
    )
    sponsor_chunk = _chunk(
        "The Batch",
        [{"url": "https://tracking.tldrnewsletter.com/CL0/sponsor/1/abc",
          "anchor_text": "Google Cloud x NVIDIA: Engineering the Future of AI (Sponsor) — Register Free"}],
    )
    result = _build_sources([story_chunk, sponsor_chunk])
    urls = [s["url"] for s in result]
    assert "https://deeplearning.ai/the-batch/issue-123" in urls
    assert "https://tracking.tldrnewsletter.com/CL0/sponsor/1/abc" in urls


# ---------------------------------------------------------------------------
# CTA anchor filter tests
# ---------------------------------------------------------------------------

def test_is_cta_link_demo_signal():
    """'Try a demo' anchor is classified as CTA."""
    assert _is_cta_link({"anchor_text": "Want to test Airia enterprise AI for yourself? Try a demo right here."})


def test_is_cta_link_learn_more():
    """'Learn more' anchor is classified as CTA."""
    assert _is_cta_link({"anchor_text": "Learn more about our platform"})


def test_is_cta_link_share_thoughts():
    """'Share your thoughts' anchor is classified as CTA."""
    assert _is_cta_link({"anchor_text": " Other (share your thoughts) "})


def test_is_cta_link_terms():
    """'Terms of service' anchor is classified as CTA."""
    assert _is_cta_link({"anchor_text": "Terms of Service"})


def test_is_cta_link_story_not_filtered():
    """A real story headline is not classified as CTA."""
    assert not _is_cta_link({"anchor_text": "New AI chip breaks records in benchmark tests"})


def test_is_cta_link_case_insensitive():
    """CTA detection is case-insensitive."""
    assert _is_cta_link({"anchor_text": "LEARN MORE"})


def test_cta_link_not_selected_when_story_link_present():
    """Within a chunk, CTA link is skipped and story link is selected instead."""
    links = [
        {"url": "https://example.com/ai-story", "anchor_text": "New AI model beats GPT-4"},
        {"url": "https://example.com/demo", "anchor_text": "Try a demo right here."},
    ]
    cluster = [_chunk("The Deep View", links)]
    result = _build_sources(cluster)
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/ai-story"


def test_cta_fallback_when_all_links_are_ctas():
    """If every link in a chunk is a CTA, fall back to unfiltered selection (do not drop chunk)."""
    links = [
        {"url": "https://example.com/demo", "anchor_text": "Try a demo"},
        {"url": "https://example.com/more", "anchor_text": "Learn more"},
    ]
    cluster = [_chunk("Newsletter A", links)]
    result = _build_sources(cluster)
    # Should return one result (fallback to best of CTAs) rather than empty
    assert len(result) == 1


def test_legitimate_sponsor_with_descriptive_anchor_kept():
    """A sponsor link with a descriptive, non-CTA anchor is NOT filtered."""
    links = [
        {"url": "https://sponsor.com/report-2026", "anchor_text": "Download the 2026 AI State of the Industry Report"},
    ]
    cluster = [_chunk("TLDR AI", links)]
    result = _build_sources(cluster)
    assert len(result) == 1
    assert result[0]["url"] == "https://sponsor.com/report-2026"


# ---------------------------------------------------------------------------
# CTA anchor filter — gap coverage (Loop 9D additions)
# ---------------------------------------------------------------------------

def test_cta_watch_now_filtered():
    """'Watch now' is classified as a CTA — was missing from _CTA_ANCHOR_SIGNALS."""
    assert _is_cta_link({"anchor_text": "Watch now"})


def test_cta_watch_now_case_insensitive():
    """'WATCH NOW' (all caps) is also classified as CTA — detection is case-insensitive."""
    assert _is_cta_link({"anchor_text": "WATCH NOW"})


def test_cta_get_the_report_filtered():
    """'get the report' is classified as a CTA lead-gen pattern."""
    assert _is_cta_link({"anchor_text": "get the report"})


def test_cta_see_it_in_action_filtered():
    """'see it in action' is classified as a CTA demo/interactive pattern."""
    assert _is_cta_link({"anchor_text": "See it in action"})


# ---------------------------------------------------------------------------
# _score_source anchor word-count cap tests (Loop 9D — Phase 4)
# Confirmed against actual Deep View diagnostic output (Task 8).
# ---------------------------------------------------------------------------

def test_score_source_prose_anchor_penalized():
    """A 14-word in-text prose anchor (WALL-E case) returns anchor_score=0."""
    anchor = "small robots that looked like they came straight out of WALL-E"
    score = _score_source({"url": "https://example.com/a/b/c", "anchor_text": anchor})
    assert score[1] == 0, f"Expected anchor_score=0 for 14-word anchor, got {score[1]}"


def test_score_source_headline_beats_prose_at_same_depth():
    """A 5-word headline outscores a 14-word prose anchor when path depth is equal."""
    url = "https://example.com/robots/keynote/video"  # path_depth=3 for both
    prose = _score_source({"url": url, "anchor_text": "small robots that looked like they came straight out of WALL-E"})
    headline = _score_source({"url": url, "anchor_text": "Nvidia GTC robotics keynote"})  # 4 words
    assert headline > prose, (
        f"Headline score {headline} should beat prose score {prose} at equal path depth"
    )


def test_score_source_short_anchor_uncapped():
    """A 5-word anchor returns anchor_score=5 (not penalized, at or below cap)."""
    score = _score_source({"url": "https://example.com/a", "anchor_text": "Nvidia GTC robotics keynote"})  # 4 words
    assert score[1] == 4


def test_score_source_boundary_at_seven_words():
    """Exactly 7 words → anchor_score=7 (boundary is inclusive). 8 words → anchor_score=0."""
    url = "https://example.com/a"
    assert _ANCHOR_IDEAL_MAX_WORDS == 7, "Boundary test assumes threshold of 7"
    at_boundary = _score_source({"url": url, "anchor_text": "one two three four five six seven"})
    over_boundary = _score_source({"url": url, "anchor_text": "one two three four five six seven eight"})
    assert at_boundary[1] == 7, f"Expected 7 at boundary, got {at_boundary[1]}"
    assert over_boundary[1] == 0, f"Expected 0 over boundary, got {over_boundary[1]}"


def test_score_source_path_depth_still_primary():
    """A penalized prose anchor at path_depth=3 beats an unpenalized short anchor at path_depth=2."""
    prose_deep = _score_source({
        "url": "https://example.com/a/b/c",  # depth=3
        "anchor_text": "small robots that looked like they came straight out of WALL-E",  # 14w → score 0
    })
    headline_shallow = _score_source({
        "url": "https://example.com/a/b",  # depth=2
        "anchor_text": "Nvidia GTC keynote",  # 3w → score 3
    })
    assert prose_deep > headline_shallow, (
        f"Deeper path {prose_deep} should beat shallower even when anchor is penalized; "
        f"got prose_deep={prose_deep}, headline_shallow={headline_shallow}"
    )
