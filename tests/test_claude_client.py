from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.claude_client import _BATCH_SIZE


def test_batch_size_value():
    """_BATCH_SIZE must be 15 (conservative ceiling for verbose entries, 8192 token limit)."""
    assert _BATCH_SIZE == 15, (
        f"_BATCH_SIZE is {_BATCH_SIZE}, expected 15. "
        "Update this test and the inline comment in claude_client.py together."
    )


def test_batch_split_50_groups():
    """50 story groups split into ceil(50/15) = 4 batches: 15, 15, 15, 5."""
    groups = list(range(50))  # stand-in for StoryGroup objects; split logic is identical
    batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
    assert len(batches) == 4
    assert len(batches[0]) == 15
    assert len(batches[1]) == 15
    assert len(batches[2]) == 15
    assert len(batches[3]) == 5


def test_batch_split_single_group():
    """1 story group produces 1 batch of 1."""
    groups = [object()]
    batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_batch_split_exactly_one_batch():
    """15 story groups produce exactly 1 batch."""
    groups = list(range(15))
    batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
    assert len(batches) == 1
    assert len(batches[0]) == 15


def test_batch_split_16_groups():
    """16 story groups produce 2 batches: 15, 1."""
    groups = list(range(16))
    batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
    assert len(batches) == 2
    assert len(batches[0]) == 15
    assert len(batches[1]) == 1


def test_batch_split_preserves_order():
    """Concatenating batch slices reproduces the original input order exactly."""
    groups = list(range(50))
    batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
    merged = []
    for batch in batches:
        merged.extend(batch)
    assert merged == groups, "Batch concatenation must reproduce the original input order"


# ---------------------------------------------------------------------------
# Retry-split arithmetic tests (truncation recovery)
# ---------------------------------------------------------------------------

def _retry_halves(batch: list) -> tuple[list, list]:
    """Mirror the ceiling-split used in generate_digest() truncation recovery."""
    split = len(batch) // 2 + len(batch) % 2
    return batch[:split], batch[split:]


def test_retry_split_15_entries():
    """15-entry batch splits into ceiling half of 8 and lower half of 7."""
    batch = list(range(15))
    half_a, half_b = _retry_halves(batch)
    assert len(half_a) == 8
    assert len(half_b) == 7
    assert half_a + half_b == batch, "Halves must reconstruct the original batch in order"


def test_retry_split_1_entry():
    """Single-entry batch: half_a has 1 entry, half_b is empty — no entry lost."""
    batch = [0]
    half_a, half_b = _retry_halves(batch)
    assert len(half_a) == 1
    assert len(half_b) == 0
    assert half_a + half_b == batch


def test_retry_split_2_entries():
    """Two-entry batch: each half gets exactly 1 entry."""
    batch = [0, 1]
    half_a, half_b = _retry_halves(batch)
    assert len(half_a) == 1
    assert len(half_b) == 1
    assert half_a + half_b == batch
