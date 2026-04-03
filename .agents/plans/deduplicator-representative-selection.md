# Feature: deduplicator-representative-selection

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to the import chain: `email_parser` → `embedder` → `deduplicator`. All three are affected. Read each file in full before touching it.

## Feature Description

Rewrite `processing/deduplicator.py` to accept clusters of `StoryRecord` objects and return one `StoryRecord` per cluster — the **representative** — selected by the priority rule: longest body → has title → has link. Override the representative's date with the earliest date in its cluster.

Also update `processing/embedder.py` to replace its `ParsedEmail`/`StoryChunk` interface with `StoryRecord`, since it is the upstream stage that feeds `deduplicator.py` and it still imports the now-deleted `ParsedEmail`.

## User Story

As `digest_builder.py` (the pipeline orchestrator),
I want `deduplicate()` to accept clusters of `StoryRecord` objects and return one `StoryRecord` per cluster
So that the downstream LLM filter receives a flat, deduplicated list of individually addressable story items with the correct shape.

## Problem Statement

`ingestion/email_parser.py` has been rewritten to return `list[StoryRecord]` (Phase 1+2 complete). Neither `processing/embedder.py` nor `processing/deduplicator.py` have been updated:

- `embedder.py` still imports the deleted `ParsedEmail` class and defines a `StoryChunk` dataclass that no longer exists in the architecture. It segments emails into chunks — work now done by `email_parser.py`. It will `ImportError` on startup.
- `deduplicator.py` imports `StoryChunk` from `embedder.py` and returns `list[StoryGroup]` — a shape that no longer matches the pipeline. `StoryGroup` bundles multiple chunks with a `sources` list; the new architecture requires one `StoryRecord` per deduplicated cluster.

## Scope

- **In scope:**
  - `processing/embedder.py` — interface update: remove `ParsedEmail`/`StoryChunk`/`_segment_email`; update `embed_and_cluster()` to accept `list[StoryRecord]` → return `list[list[StoryRecord]]`
  - `processing/deduplicator.py` — full rewrite: remove `StoryGroup`/`_build_sources`/`_is_cta_link`/`_score_source`; add `select_representative()`; rewrite `deduplicate()` to return `list[StoryRecord]`
  - `tests/test_deduplicator.py` — replace old `_build_sources`/CTA/scoring tests with `select_representative` and `deduplicate` tests

- **Out of scope:**
  - `processing/digest_builder.py` — separate plan
  - `ai/claude_client.py` — separate plan
  - API routes, frontend — separate plan
  - The core sentence-transformers encoding and `community_detection` call inside `embed_and_cluster()` — algorithm unchanged, only the wrapper types change

## Solution Statement

**embedder.py:** Strip segmentation logic (now owned by `email_parser.py`). Replace `ParsedEmail`→`StoryRecord` throughout. Remove `StoryChunk`. Update `embed_and_cluster()` to encode `record.body[:_MAX_ENCODING_CHARS]` for each `StoryRecord`. The clustering algorithm itself is untouched.

**deduplicator.py:** Replace merged-sources logic with `select_representative()`. Selection key: `(len(r.body), r.title is not None, r.link is not None)` — maximise each in order. After selection, override `date` with the earliest date in the cluster using `dataclasses.replace()`. `deduplicate()` maps this over all clusters and returns a flat `list[StoryRecord]`.

**Why remove `_is_cta_link` / `_score_source`?** These scored links across multiple chunks to build a `sources` list. In the new architecture, `StoryRecord.link` is already the pre-selected best link for that section (chosen by `_select_link()` in `email_parser.py`). There is no pool of links to score across — the representative item's link is used as-is.

**Why remove `_segment_email` from embedder?** `email_parser.py` now outputs one `StoryRecord` per section. Segmentation is complete before the embedder receives anything.

## Feature Metadata

**Feature Type:** Refactor
**Estimated Complexity:** Low
**Primary Systems Affected:** `processing/embedder.py`, `processing/deduplicator.py`, `tests/test_deduplicator.py`
**Dependencies:** `ingestion.email_parser.StoryRecord` (implemented), `sentence_transformers` (already installed), `config.settings` (already used)
**Assumptions:**
- `ingestion/email_parser.py` Phase 1+2 is complete — `StoryRecord` is importable and `parse_emails()` returns `list[StoryRecord]`
- `sentence_transformers` and its `community_detection` utility are installed and working
- A `.env` file exists locally (required by `config.Settings()` at import time)

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `processing/embedder.py` (full file) — current state: imports `ParsedEmail`, defines `StoryChunk`, `_segment_email()`, `embed_and_cluster()`. Understand fully before modifying — the clustering algorithm at lines 169–188 is kept exactly.
- `processing/deduplicator.py` (full file) — current state: imports `StoryChunk`, defines `StoryGroup`, `_build_sources()`, `_is_cta_link()`, `_score_source()`, `deduplicate()`. Almost everything is replaced.
- `ingestion/email_parser.py` (lines 210–216) — `StoryRecord` dataclass definition. This is the type that flows through the new pipeline.
- `tests/test_deduplicator.py` (full file) — current tests; all will be replaced. Read to understand what was tested so equivalent coverage is maintained where relevant.
- `CLAUDE.md` — representative selection rule, dedup signal (body text), "never drop by length" constraint, `StoryRecord` shape.
- `config.py` — `settings.dedup_threshold` used in `embed_and_cluster()`.

### Files to Modify

- `processing/embedder.py`
- `processing/deduplicator.py`
- `tests/test_deduplicator.py`

### New Files

None.

### Relevant Documentation

No new external dependencies. `dataclasses.replace()` is stdlib — no docs needed beyond knowing it creates a shallow copy with overridden fields.

### Patterns to Follow

**StoryRecord dataclass** (`ingestion/email_parser.py:210–216`):
```python
@dataclass
class StoryRecord:
    title: str | None
    body: str
    link: str | None
    newsletter: str
    date: str            # YYYY-MM-DD or empty string
```

**dataclasses.replace() for immutable field override:**
```python
import dataclasses
new_record = dataclasses.replace(record, date="2026-03-10")
```
Returns a new `StoryRecord` with all fields copied except `date`. Does not mutate the original.

**Logging pattern** (throughout both files):
```python
logger = logging.getLogger(__name__)
logger.info("Clustered %d story records into %d groups (threshold=%.2f)", ...)
logger.warning("Large cluster (%d items from %s) — possible false positive merge", ...)
```

**Lazy model loading** (`embedder.py:59–75`) — keep unchanged:
```python
_model: SentenceTransformer | None = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model
```

**Test helper pattern** (`tests/test_deduplicator.py:11–12`):
```python
def _chunk(sender: str, links: list[dict]) -> StoryChunk:
    return StoryChunk(text="test text", sender=sender, links=links)
```
Mirror with a `_record()` helper using `StoryRecord`.

**Test file sys.path pattern** (`tests/test_deduplicator.py:3–5`):
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
Keep this — required for test discovery without package install.

---

## IMPLEMENTATION PLAN

### Phase 1: Update `processing/embedder.py`

Remove `ParsedEmail`/`StoryChunk`/segmentation. Update `embed_and_cluster()` to work with `StoryRecord`. The clustering algorithm (lines 169–188 of current file) is not changed.

### Phase 2: Rewrite `processing/deduplicator.py`

Remove `StoryGroup`, `_build_sources`, `_is_cta_link`, `_score_source` and all their support constants. Add `select_representative()`. Rewrite `deduplicate()` to return `list[StoryRecord]`.

### Phase 3: Update `tests/test_deduplicator.py`

Replace old tests with tests for the new interface. Add `_record()` helper. Cover all representative selection rules and `deduplicate()` edge cases.

---

## STEP-BY-STEP TASKS

### TASK 1 — UPDATE `processing/embedder.py`: remove old interface, update to StoryRecord

- **REMOVE** the following from `processing/embedder.py`:
  - `from ingestion.email_parser import ParsedEmail` import
  - `_SPLIT_PATTERN` regex constant
  - `_MIN_CHUNK_CHARS` constant
  - `_NON_STORY_SIGNALS` tuple
  - `_is_non_story_chunk()` function
  - `StoryChunk` dataclass (entire definition including `field` import)
  - `_segment_email()` function (entire definition)

- **ADD** import at top: `from ingestion.email_parser import StoryRecord`

- **UPDATE** `from dataclasses import dataclass, field` → `from dataclasses import dataclass` (only `dataclass` is still needed for... wait, actually `StoryChunk` is the only dataclass in this file; once removed, `dataclass` itself is no longer needed). Remove the entire `from dataclasses import ...` line.

- **UPDATE** `_encoding_text()`:
```python
def _encoding_text(record: StoryRecord) -> str:
    """Return the text used for semantic encoding (body text, truncated)."""
    return record.body[:_MAX_ENCODING_CHARS]
```

- **UPDATE** `embed_and_cluster()` signature and body. Keep the clustering algorithm (model.encode + community_detection) exactly as-is, only change the types:
```python
def embed_and_cluster(story_records: list[StoryRecord]) -> list[list[StoryRecord]]:
    """Encode story records and cluster by semantic similarity.

    Args:
        story_records: Flat list of StoryRecord objects from parse_emails().
                       Body text is used as the dedup signal.

    Returns:
        List of story clusters. Each cluster is a list of StoryRecords that
        cover the same story. Singletons (unique stories) are returned as
        single-element clusters. Every record is in exactly one cluster.
    """
    if not story_records:
        return []

    if len(story_records) == 1:
        return [[story_records[0]]]

    model = _get_model()
    encoding_texts = [_encoding_text(r) for r in story_records]
    embeddings = model.encode(encoding_texts, convert_to_tensor=True, show_progress_bar=False)

    clusters_indices = st_util.community_detection(
        embeddings,
        threshold=settings.dedup_threshold,
        min_community_size=1,
        show_progress_bar=False,
    )

    result = [[story_records[i] for i in cluster] for cluster in clusters_indices]

    logger.info(
        "Clustered %d story records into %d groups (threshold=%.2f)",
        len(story_records),
        len(result),
        settings.dedup_threshold,
    )
    return result
```

- **GOTCHA:** `re` is only imported for `_SPLIT_PATTERN`. Once `_SPLIT_PATTERN` is removed, remove `import re` too.
- **GOTCHA:** The `field` import from `dataclasses` was used by `StoryChunk`. Remove it once `StoryChunk` is gone. If no dataclass remains in the file, remove the entire `from dataclasses import ...` line.
- **GOTCHA:** `_MAX_ENCODING_CHARS = 400` is still used by `_encoding_text()` — keep it.
- **GOTCHA:** Do NOT change `_MODEL_NAME`, `_get_model()`, or the `_model` singleton — these are unchanged.
- **VALIDATE:** `python -m py_compile processing/embedder.py && echo "syntax ok"`

---

### TASK 2 — REWRITE `processing/deduplicator.py`

Replace the entire file content with the following:

```python
from __future__ import annotations

import dataclasses
import logging

from ingestion.email_parser import StoryRecord

logger = logging.getLogger(__name__)


def select_representative(cluster: list[StoryRecord]) -> StoryRecord:
    """Select the representative story item from a cluster of duplicates.

    Selection priority (higher is better, applied left-to-right as a tuple key):
    1. Longest body — maximises content richness; body text is the dedup signal
    2. Has title — structured items preferred over untitled ones as tiebreaker
    3. Has link — items with a real content URL are preferable as tiebreaker

    After selection, the representative's date is replaced with the earliest
    date across all items in the cluster. This ensures that when the same story
    appears across multiple newsletter issues, the pipeline keeps the first-seen
    date rather than the date of whichever item happened to have the longest body.

    Args:
        cluster: Non-empty list of StoryRecord objects from one semantic cluster.

    Returns:
        A new StoryRecord (via dataclasses.replace) with the representative's
        fields and the earliest date from the cluster.
    """
    representative = max(
        cluster,
        key=lambda r: (len(r.body), r.title is not None, r.link is not None),
    )
    earliest_date = min(
        (r.date for r in cluster if r.date),
        default=representative.date,
    )
    return dataclasses.replace(representative, date=earliest_date)


def deduplicate(clusters: list[list[StoryRecord]]) -> list[StoryRecord]:
    """Select one representative StoryRecord per cluster.

    Converts the list of clusters produced by embed_and_cluster() into a flat
    list of story items ready for the LLM filter. Each cluster yields exactly
    one representative item via select_representative().

    Args:
        clusters: List of story clusters from embed_and_cluster(). Each cluster
                  is a list of StoryRecords covering the same story event.

    Returns:
        Flat list of representative StoryRecord objects, one per non-empty cluster.
        Empty clusters are skipped. Order matches the cluster order from the embedder.
    """
    if not clusters:
        return []

    representatives: list[StoryRecord] = []
    for cluster in clusters:
        if not cluster:
            continue
        if len(cluster) > 5:
            newsletters = [r.newsletter for r in cluster]
            logger.warning(
                "Large cluster (%d items from %s) — possible false positive merge",
                len(cluster),
                newsletters,
            )
        representatives.append(select_representative(cluster))

    logger.info(
        "Deduplicated %d cluster(s) into %d representative story item(s)",
        len(clusters),
        len(representatives),
    )
    return representatives
```

- **GOTCHA:** `dataclasses.replace()` requires `import dataclasses` (the module), not `from dataclasses import replace`. Use `dataclasses.replace(obj, field=value)`.
- **GOTCHA:** `min()` with a generator and `default=` is Python 3.4+. The project uses 3.11+ — fine.
- **GOTCHA:** `StoryRecord.date` is `str`, not `datetime`. Lexicographic `min()` on `YYYY-MM-DD` strings gives the correct chronological minimum.
- **GOTCHA:** The `default=representative.date` in `min()` handles clusters where every item has an empty-string date — returns the representative's own date (empty string) unchanged.
- **VALIDATE:** `python -m py_compile processing/deduplicator.py && echo "syntax ok"`

---

### TASK 3 — REWRITE `tests/test_deduplicator.py`

Replace the entire file content with the following:

```python
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import StoryRecord
from processing.deduplicator import select_representative, deduplicate


def _record(
    body: str,
    title: str | None = None,
    link: str | None = None,
    newsletter: str = "Test Newsletter",
    date: str = "2026-03-17",
) -> StoryRecord:
    """Build a minimal StoryRecord for testing."""
    return StoryRecord(title=title, body=body, link=link, newsletter=newsletter, date=date)


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
    no_link = _record("Equal body text here.", title="Headline", link=None)
    with_link = _record("Equal body text here.", title="Headline", link="https://example.com/story")
    result = select_representative([no_link, with_link])
    assert result.link == "https://example.com/story"


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
    """A cluster with more than 5 items does not raise — warning is logged but processing continues."""
    cluster = [_record(f"Story item {i} with enough body text to be valid.", date=f"2026-03-{10+i:02d}") for i in range(7)]
    result = deduplicate([cluster])
    assert len(result) == 1
```

- **REMOVE** all old tests (the entire previous content is replaced).
- **GOTCHA:** This test file does NOT import from `processing.embedder`. This avoids triggering `config.Settings()` loading (which requires `.env`) in test runs that only test deduplication logic.
- **VALIDATE:** `python -m pytest tests/test_deduplicator.py -v`

---

## TESTING STRATEGY

### Unit Tests

All tests are pure unit tests — no I/O, no model loading, no `.env` required. `StoryRecord` is imported directly from `ingestion.email_parser`. `select_representative()` and `deduplicate()` are tested in isolation.

### Coverage

- `select_representative`: 8 tests covering all three selection dimensions, date override, mutation safety, edge cases (all-empty dates, partial empty dates, three-item cluster)
- `deduplicate`: 8 tests covering empty input, empty sub-clusters, single/multiple clusters, return type, date propagation, large-cluster handling

### Edge Cases

- Empty cluster list → `[]`
- Empty sub-cluster in list → skipped
- All dates empty → date unchanged
- Representative has later date than another item → date overridden with earliest
- Cluster with >5 items → warning logged, result returned normally

---

## VALIDATION COMMANDS

### Level 1: Syntax

```bash
python -m py_compile processing/embedder.py && echo "embedder syntax ok"
python -m py_compile processing/deduplicator.py && echo "deduplicator syntax ok"
```

### Level 2: Unit Tests

```bash
python -m pytest tests/test_deduplicator.py -v
```

### Level 3: Import Smoke Test

```bash
python -c "
from ingestion.email_parser import StoryRecord
from processing.deduplicator import select_representative, deduplicate
r1 = StoryRecord(title=None, body='Short body.', link=None, newsletter='A', date='2026-03-10')
r2 = StoryRecord(title='Headline', body='Longer body with more content.', link='https://example.com', newsletter='B', date='2026-03-17')
rep = select_representative([r1, r2])
print('representative body:', rep.body[:40])
print('representative date (should be earliest):', rep.date)
result = deduplicate([[r1, r2]])
print('deduplicate output count:', len(result))
print('All ok')
"
```

Expected output:
```
representative body: Longer body with more content.
representative date (should be earliest): 2026-03-10
deduplicate output count: 1
All ok
```

### Level 4: Full Test Suite (no regressions)

```bash
python -m pytest tests/ -v
```

Expected: all `test_email_parser.py` tests still pass; `test_deduplicator.py` tests all pass.

### Level 5: Cluster Inspection — Human-Readable Dedup Report

Two sub-steps. Run both.

**5a — Synthetic clusters (no model loading):**

Directly calls `deduplicate()` with hand-crafted clusters that each exercise a different selection rule. No sentence-transformers model required. Confirms selection logic is correct and output is readable.

```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import StoryRecord
from processing.deduplicator import deduplicate

def _r(body, title=None, link=None, newsletter='NL', date='2026-03-17'):
    return StoryRecord(title=title, body=body, link=link, newsletter=newsletter, date=date)

clusters = [
    # Cluster A: longest body wins; date override from earlier item
    [
        _r('Short version of the story.', newsletter='TLDR AI', date='2026-03-10'),
        _r('Nvidia announced several new robotics platforms at GTC 2026, including a full-stack approach to physical AI with new chips, software, and partnerships with leading robotics manufacturers.',
           title='Nvidia bets on robotics', link='https://techcrunch.com/nvidia-gtc', newsletter='The Deep View', date='2026-03-17'),
    ],
    # Cluster B: all same body length — title breaks tie
    [
        _r('Same body length here!', title=None, newsletter='NL A', date='2026-03-15'),
        _r('Same body length here!', title='Headline wins', link='https://example.com/story', newsletter='NL B', date='2026-03-17'),
    ],
    # Cluster C: singleton — returned as-is
    [
        _r('OpenAI cut API prices for GPT-4o by 50 percent starting this week.', link='https://openai.com/pricing', newsletter='AI Breakfast', date='2026-03-14'),
    ],
]

reps = deduplicate(clusters)

for i, (cluster, rep) in enumerate(zip(clusters, reps), 1):
    # Identify representative by index (mirrors select_representative key) so
    # items with identical body+newsletter are not falsely marked as [REPRESENTATIVE]
    rep_idx = max(range(len(cluster)), key=lambda j: (
        len(cluster[j].body), cluster[j].title is not None, cluster[j].link is not None
    ))
    print(f'=== Cluster {i} ({len(cluster)} item(s)) ===')
    for j, item in enumerate(cluster):
        marker = '[REPRESENTATIVE]' if j == rep_idx else '[ duplicate    ]'
        print(f'  {marker}  newsletter={item.newsletter!r:20s}  date={item.date}  body_len={len(item.body):4d}  title={item.title!r}')
        print(f'               body: {item.body[:80]!r}')
    print(f'  -> selected date (earliest): {rep.date}')
    print()
"
```

Expected output shape (exact body text will match above):
```
=== Cluster 1 (2 items) ===
  [ duplicate    ]  newsletter='TLDR AI'              date=2026-03-10  body_len=  26  title=None
                 body: 'Short version of the story.'
  [REPRESENTATIVE]  newsletter='The Deep View'        date=2026-03-17  body_len= 180  title='Nvidia bets on robotics'
                 body: 'Nvidia announced several new robotics platforms at GTC 2026, including a full-'
  → selected date (earliest): 2026-03-10

=== Cluster 2 (2 items) ===
  [ duplicate    ]  newsletter='NL A'                 date=2026-03-15  body_len=  21  title=None
                 body: 'Same body length here!'
  [REPRESENTATIVE]  newsletter='NL B'                 date=2026-03-17  body_len=  21  title='Headline wins'
                 body: 'Same body length here!'
  → selected date (earliest): 2026-03-15

=== Cluster 3 (1 item(s)) ===
  [REPRESENTATIVE]  newsletter='AI Breakfast'         date=2026-03-14  body_len=  65  title=None
                 body: 'OpenAI cut API prices for GPT-4o by 50 percent starting this week.'
  → selected date (earliest): 2026-03-14
```

Verify:
- Cluster 1: The Deep View item is `[REPRESENTATIVE]` (longer body); date is `2026-03-10` (from the TLDR AI item)
- Cluster 2: NL B item is `[REPRESENTATIVE]` (same body length, but has title); date is `2026-03-15` (from NL A item)
- Cluster 3: Singleton returned unchanged

**5b — Real email end-to-end (requires model, ~10s first run):**

Runs the full pipeline on a real email file: `parse_emails → embed_and_cluster → deduplicate`. Shows every cluster with all items and the selected representative.

Requires `debug_samples/the_deep_view.eml` to exist. Skip if not present.

```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails
from processing.embedder import embed_and_cluster
from processing.deduplicator import deduplicate

with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()

records = parse_emails([raw])
print(f'Parsed: {len(records)} story records')

clusters = embed_and_cluster(records)
print(f'Clustered: {len(clusters)} groups ({sum(len(c) for c in clusters if len(c) > 1)} items in multi-item clusters)')

reps = deduplicate(clusters)
print(f'Deduplicated: {len(reps)} representatives')
print()

multi = [(c, r) for c, r in zip(clusters, reps) if len(c) > 1]
if not multi:
    print('No multi-item clusters found (all stories are unique in this email).')
else:
    print(f'=== {len(multi)} multi-item cluster(s) ===')
    for i, (cluster, rep) in enumerate(multi, 1):
        rep_idx = max(range(len(cluster)), key=lambda j: (
            len(cluster[j].body), cluster[j].title is not None, cluster[j].link is not None
        ))
        print(f'--- Group {i} ({len(cluster)} items) ---')
        for j, item in enumerate(cluster):
            marker = '[REP]' if j == rep_idx else '[dup]'
            print(f'  {marker}  body_len={len(item.body):4d}  title={item.title!r}')
            print(f'         body: {item.body[:100]!r}')
        print(f'  -> representative date: {rep.date}')
        print()

print('--- All representatives (first 5) ---')
for r in reps[:5]:
    print(f'  date={r.date}  newsletter={r.newsletter!r}  title={r.title!r}')
    print(f'  body: {r.body[:80]!r}')
    print()
"
```

Expected output shape:
```
Parsed: 45 story records
Clustered: N groups (M items in multi-item clusters)
Deduplicated: N representatives

(multi-item clusters printed if any found)

--- All representatives (first 5) ---
  date=2026-03-17  newsletter='The Deep View'  title=None
  body: '**Welcome back.** Nvidia announced...'
  ...
```

Verify manually:
- Total representative count is lower than or equal to parsed record count (dedup collapsed some)
- Any multi-item clusters shown have one `[REP]` and the rest `[dup]`
- The `[REP]` in each cluster has the longest body among its cluster members
- The representative date equals the earliest date in the cluster

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `from processing.deduplicator import select_representative, deduplicate` imports without error
- [ ] `from processing.embedder import embed_and_cluster` imports without error
- [ ] `StoryChunk` no longer exists in `processing/embedder.py`
- [ ] `StoryGroup` no longer exists in `processing/deduplicator.py`
- [ ] `_build_sources` no longer exists in `processing/deduplicator.py`
- [ ] `ParsedEmail` no longer imported in `processing/embedder.py`
- [ ] `deduplicate()` return type is `list[StoryRecord]`
- [ ] `embed_and_cluster()` accepts `list[StoryRecord]` and returns `list[list[StoryRecord]]`
- [ ] Earliest date in cluster appears on the deduplicated representative
- [ ] All 16 new deduplicator tests pass
- [ ] All 34 email_parser tests still pass

## ROLLBACK CONSIDERATIONS

All changes are in two Python files and one test file. Git revert restores all three. No database migrations, no config changes. `digest_builder.py` is not yet updated to call the new interface — it will fail with a type error until rewritten in the next plan. This is expected.

## ACCEPTANCE CRITERIA

- [ ] `embed_and_cluster()` accepts `list[StoryRecord]`, returns `list[list[StoryRecord]]`
- [ ] `select_representative()` selects by: longest body → has title → has link
- [ ] `select_representative()` sets date to earliest in cluster
- [ ] `select_representative()` does not mutate input records
- [ ] `deduplicate()` returns `list[StoryRecord]`, one per non-empty cluster
- [ ] All 16 new tests pass; all 34 email_parser tests still pass
- [ ] No `ParsedEmail`, `StoryChunk`, `StoryGroup`, `_build_sources` references remain in modified files
- [ ] Syntax checks pass for both modified files

---

## COMPLETION CHECKLIST

- [ ] Task 1 complete: `embedder.py` updated
- [ ] Task 2 complete: `deduplicator.py` rewritten
- [ ] Task 3 complete: `test_deduplicator.py` replaced
- [ ] `python -m py_compile processing/embedder.py` passes
- [ ] `python -m py_compile processing/deduplicator.py` passes
- [ ] `python -m pytest tests/test_deduplicator.py -v` — 16 passed
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] Import smoke test output matches expected

---

## NOTES

**Why embedder.py is in this plan:** The prime summary marked embedder as "no changes needed (clustering logic unchanged)." That assessment referred to the `community_detection` algorithm, which is indeed untouched. But the input/output types must change to match the new pipeline, and since `deduplicator.py` depends on `embedder.py`'s output type, both must be updated together.

**Why CTA/scoring logic is removed:** `_is_cta_link()` and `_score_source()` were used by `_build_sources()` to select the best link from a pool of links across multiple chunks. In the new architecture, each `StoryRecord.link` is already the pre-selected best link for its section (chosen by `_select_link()` in `email_parser.py`). There is no cross-chunk link pool to score, so the scoring logic has no role.

The prime summary's note "CTA and scoring tests still valid" reflected an earlier assessment before the full implications of the `email_parser.py` rewrite were clear. Those functions no longer have a call site in the new architecture.

**`dataclasses.replace()` vs mutation:** The spec says "representative selection" implies choosing an existing item, but the date override means the returned item cannot be the input record unchanged. `dataclasses.replace()` creates a new instance with overridden fields — correct for an immutable data flow.

**Plain-text emails:** `embed_and_cluster()` previously fell back to splitting plain-text bodies when HTML was unavailable. That fallback is now gone — plain-text emails that produce no `StoryRecord`s (already handled by `parse_emails()`) simply won't appear in the input list. This matches the design: `email_parser.py` owns all parsing decisions.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `python -m py_compile processing/embedder.py && echo "embedder syntax ok"`
  Expected output or result:
  `embedder syntax ok`

- Item to check:
  `python -m py_compile processing/deduplicator.py && echo "deduplicator syntax ok"`
  Expected output or result:
  `deduplicator syntax ok`

- Item to check:
  `python -m pytest tests/test_deduplicator.py -v`
  Expected output or result:
  ```
  tests/test_deduplicator.py::test_single_item_cluster_returns_that_item PASSED
  tests/test_deduplicator.py::test_longest_body_wins PASSED
  tests/test_deduplicator.py::test_title_breaks_body_tie PASSED
  tests/test_deduplicator.py::test_link_breaks_remaining_tie PASSED
  tests/test_deduplicator.py::test_earliest_date_overrides_representative_date PASSED
  tests/test_deduplicator.py::test_original_record_not_mutated PASSED
  tests/test_deduplicator.py::test_all_empty_dates_preserves_representative_date PASSED
  tests/test_deduplicator.py::test_representative_date_from_partial_empty_dates PASSED
  tests/test_deduplicator.py::test_three_item_cluster_selects_longest PASSED
  tests/test_deduplicator.py::test_deduplicate_empty_clusters_returns_empty PASSED
  tests/test_deduplicator.py::test_deduplicate_skips_empty_clusters PASSED
  tests/test_deduplicator.py::test_deduplicate_single_cluster_single_item PASSED
  tests/test_deduplicator.py::test_deduplicate_single_cluster_multiple_items PASSED
  tests/test_deduplicator.py::test_deduplicate_multiple_clusters_one_per_cluster PASSED
  tests/test_deduplicator.py::test_deduplicate_returns_story_records PASSED
  tests/test_deduplicator.py::test_deduplicate_date_override_propagates PASSED
  tests/test_deduplicator.py::test_deduplicate_large_cluster_no_exception PASSED
  17 passed
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import StoryRecord
  from processing.deduplicator import select_representative, deduplicate
  r1 = StoryRecord(title=None, body='Short body.', link=None, newsletter='A', date='2026-03-10')
  r2 = StoryRecord(title='Headline', body='Longer body with more content.', link='https://example.com', newsletter='B', date='2026-03-17')
  rep = select_representative([r1, r2])
  print('representative body:', rep.body[:40])
  print('representative date (should be earliest):', rep.date)
  result = deduplicate([[r1, r2]])
  print('deduplicate output count:', len(result))
  print('All ok')
  "
  ```
  Expected output or result:
  ```
  representative body: Longer body with more content.
  representative date (should be earliest): 2026-03-10
  deduplicate output count: 1
  All ok
  ```

- Item to check:
  `python -m pytest tests/ -v` — email_parser tests
  Expected output or result:
  All 34 `test_email_parser.py` tests PASSED with no failures or errors.

- Item to check:
  Level 5a synthetic cluster inspection script (full command in Level 5a)
  Expected output or result:
  ```
  === Cluster 1 (2 items) ===
    [ duplicate    ]  newsletter='TLDR AI'              date=2026-03-10  body_len=  26  title=None
                   body: 'Short version of the story.'
    [REPRESENTATIVE]  newsletter='The Deep View'        date=2026-03-17  body_len= 180  title='Nvidia bets on robotics'
                   body: 'Nvidia announced several new robotics platforms at GTC 2026, including a full-'
    → selected date (earliest): 2026-03-10

  === Cluster 2 (2 items) ===
    [ duplicate    ]  newsletter='NL A'                 date=2026-03-15  body_len=  21  title=None
                   body: 'Same body length here!'
    [REPRESENTATIVE]  newsletter='NL B'                 date=2026-03-17  body_len=  21  title='Headline wins'
                   body: 'Same body length here!'
    → selected date (earliest): 2026-03-15

  === Cluster 3 (1 item(s)) ===
    [REPRESENTATIVE]  newsletter='AI Breakfast'         date=2026-03-14  body_len=  65  title=None
                   body: 'OpenAI cut API prices for GPT-4o by 50 percent starting this week.'
    → selected date (earliest): 2026-03-14
  ```
  Verify: Cluster 1 rep is The Deep View (longer body), date overridden to 2026-03-10. Cluster 2 rep is NL B (title tiebreaker), date overridden to 2026-03-15. Cluster 3 singleton unchanged.

- Item to check:
  Level 5b real email end-to-end inspection script (full command in Level 5b) — requires `debug_samples/the_deep_view.eml`
  Expected output or result:
  First three lines printed:
  ```
  Parsed: 45 story records
  Clustered: N groups (M items in multi-item clusters)
  Deduplicated: N representatives
  ```
  Where N representatives ≤ 45. Any multi-item clusters shown must have exactly one `[REP]` line per cluster. The `[REP]` item must have the longest `body_len` among all items in that cluster. The representative date must equal the earliest date among cluster members.

- Item to check:
  `StoryChunk` no longer exists in `processing/embedder.py`
  Expected output or result:
  `grep "StoryChunk" processing/embedder.py` returns no output (empty).

- Item to check:
  `StoryGroup` no longer exists in `processing/deduplicator.py`
  Expected output or result:
  `grep "StoryGroup" processing/deduplicator.py` returns no output (empty).

- Item to check:
  `ParsedEmail` no longer imported in `processing/embedder.py`
  Expected output or result:
  `grep "ParsedEmail" processing/embedder.py` returns no output (empty).

- Item to check:
  `_build_sources` no longer exists in `processing/deduplicator.py`
  Expected output or result:
  `grep "_build_sources" processing/deduplicator.py` returns no output (empty).
