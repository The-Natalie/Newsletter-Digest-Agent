from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import StoryRecord
from processing.deduplicator import select_representative, deduplicate


def _record(
    body: str,
    title: str | None = None,
    links: list[str] | None = None,
    newsletter: str = "Test Newsletter",
    date: str = "2026-03-17",
) -> StoryRecord:
    """Build a minimal StoryRecord for testing."""
    return StoryRecord(title=title, body=body, links=links or [], newsletter=newsletter, date=date)


# ---------------------------------------------------------------------------
# select_representative — selection priority tests
# ---------------------------------------------------------------------------

def test_single_item_cluster_returns_that_item():
    """Single-item cluster → returns the item unchanged (modulo date override)."""
    r = _record("OpenAI released GPT-5 this week with major reasoning improvements.")
    result = select_representative([r])
    assert result.body == r.body
    assert result.newsletter == r.newsletter


def test_longest_body_wins():
    """Item with the longest body is selected as representative."""
    short = _record("Short body.")
    long = _record("This is a much longer body with more detail about the story and its implications.")
    result = select_representative([short, long])
    assert result.body == long.body


def test_title_breaks_body_tie():
    """When body lengths are equal, titled item beats untitled item."""
    no_title = _record("Same length body text here.", title=None)
    with_title = _record("Same length body text here.", title="Story Headline")
    result = select_representative([no_title, with_title])
    assert result.title == "Story Headline"


def test_link_breaks_remaining_tie():
    """When body and title status are equal, linked item beats unlinked item."""
    no_links = _record("Equal body text here.", title="Headline", links=[])
    with_links = _record("Equal body text here.", title="Headline", links=["https://example.com/story"])
    result = select_representative([no_links, with_links])
    assert result.links == ["https://example.com/story"]


def test_earliest_date_overrides_representative_date():
    """Representative's date is set to the earliest date in the cluster."""
    early = _record("Short body.", date="2026-03-10")
    late_long = _record(
        "Much longer body that wins on body length selection criterion.",
        date="2026-03-17",
    )
    result = select_representative([early, late_long])
    # late_long wins on body length, but date should be earliest in cluster
    assert result.body == late_long.body
    assert result.date == "2026-03-10"


def test_original_record_not_mutated():
    """select_representative returns a new StoryRecord and does not mutate inputs."""
    r1 = _record("Short.", date="2026-03-10")
    r2 = _record("Much longer body that will be selected.", date="2026-03-17")
    original_date = r2.date
    select_representative([r1, r2])
    assert r2.date == original_date, "Input record must not be mutated"


def test_all_empty_dates_preserves_representative_date():
    """If all dates in cluster are empty strings, representative date is unchanged."""
    r1 = _record("Short.", date="")
    r2 = _record("Longer body text that will be selected.", date="")
    result = select_representative([r1, r2])
    assert result.date == ""


def test_representative_date_from_partial_empty_dates():
    """If some dates are empty and some are real, earliest real date is used."""
    no_date = _record("Short body.", date="")
    has_date = _record("Longer body wins on selection.", date="2026-03-14")
    result = select_representative([no_date, has_date])
    assert result.date == "2026-03-14"


def test_three_item_cluster_selects_longest():
    """Three-item cluster selects longest body regardless of order."""
    r1 = _record("First item, short.")
    r2 = _record("Second item, medium length body text here.")
    r3 = _record("Third item with the longest body text by a significant margin, lots of detail.")
    result = select_representative([r1, r2, r3])
    assert result.body == r3.body


# ---------------------------------------------------------------------------
# deduplicate — cluster-to-representative mapping tests
# ---------------------------------------------------------------------------

def test_deduplicate_empty_clusters_returns_empty():
    """Empty cluster list returns []."""
    assert deduplicate([]) == []


def test_deduplicate_skips_empty_clusters():
    """Empty sub-clusters are skipped without error."""
    r = _record("A valid story item with meaningful content.")
    result = deduplicate([[], [r]])
    assert len(result) == 1
    assert result[0].body == r.body


def test_deduplicate_single_cluster_single_item():
    """One cluster with one item → list with that item."""
    r = _record("Nvidia announced new robotics platforms at GTC 2026.")
    result = deduplicate([[r]])
    assert len(result) == 1
    assert result[0].body == r.body


def test_deduplicate_single_cluster_multiple_items():
    """One cluster with duplicates → one representative."""
    r1 = _record("Short duplicate.")
    r2 = _record("Longer duplicate with more content about the same story event.")
    result = deduplicate([[r1, r2]])
    assert len(result) == 1
    assert result[0].body == r2.body


def test_deduplicate_multiple_clusters_one_per_cluster():
    """Multiple clusters each yield one representative — count matches cluster count."""
    cluster_a = [_record("Story A content, fairly detailed description of events.")]
    cluster_b = [_record("Story B content, different topic with its own details.")]
    cluster_c = [_record("Story C content, third distinct story item here.")]
    result = deduplicate([cluster_a, cluster_b, cluster_c])
    assert len(result) == 3


def test_deduplicate_returns_story_records():
    """deduplicate() returns a list of StoryRecord instances."""
    r = _record("OpenAI released a new model with improved reasoning.")
    result = deduplicate([[r]])
    assert all(isinstance(item, StoryRecord) for item in result)


def test_deduplicate_date_override_propagates():
    """Earliest date in cluster appears on the returned representative."""
    early = _record("Short.", newsletter="Newsletter A", date="2026-03-10")
    late_long = _record("Longer body that wins on selection.", newsletter="Newsletter B", date="2026-03-17")
    result = deduplicate([[early, late_long]])
    assert len(result) == 1
    assert result[0].date == "2026-03-10"


def test_deduplicate_large_cluster_no_exception():
    """A cluster with more than 5 items does not raise — warning logged but processing continues."""
    cluster = [
        _record(f"Story item {i} with enough body text to be valid.", date=f"2026-03-{10 + i:02d}")
        for i in range(7)
    ]
    result = deduplicate([cluster])
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Phase 4: links merging and source_count tests
# ---------------------------------------------------------------------------

def test_select_representative_merges_links_from_cluster():
    """Links from all cluster items are merged into the representative."""
    r1 = _record("Short.", links=["https://example.com/a"])
    r2 = _record("Longer body that wins on selection.", links=["https://example.com/b"])
    result = select_representative([r1, r2])
    assert "https://example.com/a" in result.links
    assert "https://example.com/b" in result.links
    assert len(result.links) == 2


def test_select_representative_deduplicates_links():
    """Duplicate URLs across cluster items appear only once in merged links."""
    shared_url = "https://example.com/story"
    r1 = _record("Short.", links=[shared_url])
    r2 = _record("Longer body wins.", links=[shared_url, "https://example.com/other"])
    result = select_representative([r1, r2])
    assert result.links.count(shared_url) == 1
    assert len(result.links) == 2


def test_select_representative_sets_source_count():
    """source_count equals the number of items in the cluster."""
    cluster = [_record(f"Body {i}.") for i in range(3)]
    result = select_representative(cluster)
    assert result.source_count == 3


def test_select_representative_single_item_source_count_is_1():
    """Single-item cluster has source_count=1."""
    r = _record("Only item.")
    result = select_representative([r])
    assert result.source_count == 1


def test_deduplicate_source_count_set_on_representatives():
    """deduplicate() propagates source_count from clusters to output."""
    cluster = [_record(f"Story content item {i}.") for i in range(4)]
    result = deduplicate([cluster])
    assert len(result) == 1
    assert result[0].source_count == 4
