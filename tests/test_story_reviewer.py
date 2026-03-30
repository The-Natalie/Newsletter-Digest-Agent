from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.story_reviewer import _REVIEWER_BATCH_SIZE


def test_reviewer_batch_size_value():
    """_REVIEWER_BATCH_SIZE must be 25 (well under 1024 token output ceiling)."""
    assert _REVIEWER_BATCH_SIZE == 25, (
        f"_REVIEWER_BATCH_SIZE is {_REVIEWER_BATCH_SIZE}, expected 25. "
        "Update this test and the inline comment in story_reviewer.py together."
    )


def test_reviewer_batch_split_73_groups():
    """73 groups split into ceil(73/25) = 3 batches: 25, 25, 23."""
    groups = list(range(73))
    batches = [groups[i:i + _REVIEWER_BATCH_SIZE] for i in range(0, len(groups), _REVIEWER_BATCH_SIZE)]
    assert len(batches) == 3
    assert len(batches[0]) == 25
    assert len(batches[1]) == 25
    assert len(batches[2]) == 23


def test_reviewer_batch_split_single_group():
    """1 group produces 1 batch of 1."""
    groups = [object()]
    batches = [groups[i:i + _REVIEWER_BATCH_SIZE] for i in range(0, len(groups), _REVIEWER_BATCH_SIZE)]
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_reviewer_batch_split_exactly_one_batch():
    """25 groups produce exactly 1 batch."""
    groups = list(range(25))
    batches = [groups[i:i + _REVIEWER_BATCH_SIZE] for i in range(0, len(groups), _REVIEWER_BATCH_SIZE)]
    assert len(batches) == 1
    assert len(batches[0]) == 25


def test_reviewer_batch_split_26_groups():
    """26 groups produce 2 batches: 25, 1."""
    groups = list(range(26))
    batches = [groups[i:i + _REVIEWER_BATCH_SIZE] for i in range(0, len(groups), _REVIEWER_BATCH_SIZE)]
    assert len(batches) == 2
    assert len(batches[0]) == 25
    assert len(batches[1]) == 1


def test_reviewer_batch_split_preserves_order():
    """Concatenating reviewer batch slices reproduces the original input order exactly."""
    groups = list(range(73))
    batches = [groups[i:i + _REVIEWER_BATCH_SIZE] for i in range(0, len(groups), _REVIEWER_BATCH_SIZE)]
    merged = []
    for batch in batches:
        merged.extend(batch)
    assert merged == groups, "Reviewer batch concatenation must reproduce original input order"
