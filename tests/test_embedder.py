from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import StoryRecord
from processing.embedder import embed_and_cluster


def _record(body: str, title: str | None = None, newsletter: str = "Test") -> StoryRecord:
    return StoryRecord(title=title, body=body, links=[], newsletter=newsletter, date="2026-04-07")


# NOTE: these tests call the real sentence-transformers model.
# They are integration-level; each test may take ~0.5s on first run (model load).


def test_embed_and_cluster_empty_input():
    """Empty input → empty output."""
    assert embed_and_cluster([]) == []


def test_embed_and_cluster_single_item():
    """Single item → one singleton cluster containing that item."""
    r = _record("OpenAI announced a new model today.")
    result = embed_and_cluster([r])
    assert len(result) == 1
    assert len(result[0]) == 1
    assert result[0][0].body == r.body


def test_embed_and_cluster_identical_stories_same_cluster():
    """Near-identical stories are placed in the same cluster."""
    r1 = _record("OpenAI released GPT-5 with major reasoning improvements this week.")
    r2 = _record("OpenAI unveiled GPT-5 featuring significantly enhanced reasoning capabilities.")
    result = embed_and_cluster([r1, r2])
    # Both should land in one cluster (very high similarity)
    assert len(result) == 1
    assert len(result[0]) == 2


def test_embed_and_cluster_unrelated_stories_separate_clusters():
    """Unrelated stories produce separate clusters."""
    r1 = _record("The recipe calls for two cups of flour and one egg.")
    r2 = _record("NASA launched a new satellite into low Earth orbit yesterday.")
    result = embed_and_cluster([r1, r2])
    assert len(result) == 2


def test_embed_and_cluster_all_records_present():
    """Every input record appears in exactly one output cluster."""
    r1 = _record("Story A about technology and AI developments.")
    r2 = _record("Story B about space exploration and NASA missions.")
    r3 = _record("Story C about renewable energy and solar panels.")
    result = embed_and_cluster([r1, r2, r3])
    all_records = [r for cluster in result for r in cluster]
    assert len(all_records) == 3


def test_embed_and_cluster_no_record_in_multiple_clusters():
    """No record appears in more than one cluster."""
    records = [_record(f"Story {i} with unique content about a distinct topic area.") for i in range(4)]
    result = embed_and_cluster(records)
    seen_ids: set[int] = set()
    for cluster in result:
        for r in cluster:
            assert id(r) not in seen_ids, "Record appears in multiple clusters"
            seen_ids.add(id(r))
