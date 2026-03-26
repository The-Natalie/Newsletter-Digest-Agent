# Feature: processing/deduplicator.py

The following plan should be complete, but validate codebase patterns before starting.

Pay special attention to: the exact shape of `StoryGroup` (consumed by `ai/claude_client.py` next), the source-building logic (one source per unique URL, newsletter name attached to each), and the large-cluster warning from PRD §14 Risk 4.

## Feature Description

Create `processing/deduplicator.py` — the module that receives `list[list[StoryChunk]]` from `embed_and_cluster()` and converts each cluster into a `StoryGroup`: a combined view with all constituent story excerpts and a deduplicated list of source links (with newsletter attribution) ready for the AI prompt and the final API response.

## User Story

As the digest pipeline,
I want a function that takes story clusters and returns structured story groups,
So that the AI client has clean per-group input (text excerpts per newsletter + attributed source links) to generate one digest entry per unique story.

## Problem Statement

`embed_and_cluster()` returns raw clusters of `StoryChunk` objects. The AI client needs a richer structure: the combined text from all contributing newsletters (for the prompt), plus a deduplicated source list with newsletter names attached (for the digest response). Without this transformation, `digest_builder.py` would have to do structural work inline.

## Scope

- In scope: `StoryGroup` dataclass, `deduplicate()` function, `_build_sources()` private helper, large-cluster warning
- Out of scope: embedding, clustering, AI summarization, anything network-related

## Solution Statement

For each cluster (a `list[StoryChunk]`), create a `StoryGroup` that carries the full `chunks` list and a `sources` list built by iterating chunks, attaching `chunk.sender` as the `"newsletter"` key to each link, and deduplicating by URL. Warn (via `logger.warning`) on clusters larger than 5 as per PRD §14 Risk 4.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Low
**Primary Systems Affected**: `processing/deduplicator.py`
**Dependencies**: `processing.embedder.StoryChunk` (already implemented); no new third-party libraries
**Assumptions**: `StoryChunk.links` is `list[dict]` with keys `"url"` and `"anchor_text"`; `StoryChunk.sender` is the newsletter display name

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `processing/embedder.py` (lines 24–28) — `StoryChunk` definition: `text: str`, `sender: str`, `links: list[dict]`; import from here
- `ingestion/email_parser.py` (lines 1–13) — establishes the module pattern to mirror: `from __future__ import annotations`, module-level `logger = logging.getLogger(__name__)`, `@dataclass` with `field(default_factory=list)`
- `PRD.md` §7 Feature 3 (line 284) — "all contributing newsletters and their source links are recorded for that entry"
- `PRD.md` §10 API spec (lines 536–541) — exact shape of the `sources` list in the final response: `[{"newsletter": "TLDR AI", "url": "https://...", "anchor_text": "..."}]`
- `PRD.md` §14 Risk 4 (lines 715–718) — "clusters with more than 5 members are logged as warnings"

### New Files to Create

- `processing/deduplicator.py` — `StoryGroup` dataclass, `_build_sources()`, `deduplicate()`

### Patterns to Follow

**Module structure** (mirror `ingestion/email_parser.py` lines 1–13):
```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from processing.embedder import StoryChunk

logger = logging.getLogger(__name__)
```

**`StoryGroup` dataclass** (mirror `StoryChunk` in `processing/embedder.py` lines 24–28):
```python
@dataclass
class StoryGroup:
    chunks: list[StoryChunk]     # all story excerpts in this group (for AI prompt construction)
    sources: list[dict]          # [{"newsletter": str, "url": str, "anchor_text": str}]
```

**Warning pattern** (from PRD §14 Risk 4):
```python
if len(cluster) > 5:
    logger.warning("Large cluster (%d chunks) — possible false positive merge", len(cluster))
```

---

## IMPLEMENTATION PLAN

### Phase 1: Data model

Define `StoryGroup` dataclass.

### Phase 2: Source-building helper

Implement `_build_sources()` — iterate chunks, attach newsletter name, deduplicate by URL.

### Phase 3: Top-level function

Implement `deduplicate()` — map clusters to `StoryGroup` objects.

---

## STEP-BY-STEP TASKS

### TASK 1 — CREATE `processing/deduplicator.py`

This is a single-file, two-function module. All tasks build the same file.

- **IMPORTS**:
  ```python
  from __future__ import annotations

  import logging
  from dataclasses import dataclass, field

  from processing.embedder import StoryChunk

  logger = logging.getLogger(__name__)
  ```

- **`StoryGroup` dataclass**:
  ```python
  @dataclass
  class StoryGroup:
      chunks: list[StoryChunk]   # all story excerpts (for AI prompt)
      sources: list[dict] = field(default_factory=list)
      # sources shape: [{"newsletter": str, "url": str, "anchor_text": str}]
  ```
  - `chunks` carries the full `StoryChunk` objects — the AI client reads `chunk.text` and `chunk.sender`
  - `sources` is the deduplicated link list — included verbatim in the final API response

- **`_build_sources(cluster: list[StoryChunk]) -> list[dict]`** — private helper:
  - Iterate over each `chunk` in the cluster
  - For each `link` in `chunk.links`:
    - Create `{"newsletter": chunk.sender, "url": link["url"], "anchor_text": link["anchor_text"]}`
  - Deduplicate by URL (keep first occurrence of each URL; use a `seen_urls: set[str]` guard)
  - If a chunk has **no links**: add a source entry with `{"newsletter": chunk.sender, "url": "", "anchor_text": ""}` — preserves newsletter attribution even without a link
  - Deduplicate empty-URL entries by sender (one nameless entry per sender at most)
  - Return the collected `list[dict]`

  **Full implementation**:
  ```python
  def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
      """Build deduplicated source list from all chunks in a cluster."""
      sources = []
      seen_urls: set[str] = set()
      seen_empty_senders: set[str] = set()

      for chunk in cluster:
          if chunk.links:
              for link in chunk.links:
                  url = link.get("url", "")
                  if url and url not in seen_urls:
                      seen_urls.add(url)
                      sources.append({
                          "newsletter": chunk.sender,
                          "url": url,
                          "anchor_text": link.get("anchor_text", ""),
                      })
          else:
              # No links — still record the newsletter for attribution
              if chunk.sender not in seen_empty_senders:
                  seen_empty_senders.add(chunk.sender)
                  sources.append({
                      "newsletter": chunk.sender,
                      "url": "",
                      "anchor_text": "",
                  })

      return sources
  ```

- **`deduplicate(clusters: list[list[StoryChunk]]) -> list[StoryGroup]`** — public function:
  - Guard: `if not clusters: return []`
  - For each cluster:
    - Log warning if `len(cluster) > 5`
    - Build sources with `_build_sources(cluster)`
    - Append `StoryGroup(chunks=cluster, sources=sources)`
  - Return the list

  **Full implementation**:
  ```python
  def deduplicate(clusters: list[list[StoryChunk]]) -> list[StoryGroup]:
      """Convert story clusters into StoryGroup objects with combined source attribution.

      Args:
          clusters: List of story clusters from embed_and_cluster(). Each cluster is
                    a list of StoryChunks that cover the same story event.

      Returns:
          List of StoryGroup objects, one per cluster. Each group contains all
          contributing story excerpts and a deduplicated list of source links.
      """
      if not clusters:
          return []

      groups = []
      for cluster in clusters:
          if len(cluster) > 5:
              senders = [c.sender for c in cluster]
              logger.warning(
                  "Large cluster (%d chunks from %s) — possible false positive merge",
                  len(cluster),
                  senders,
              )
          sources = _build_sources(cluster)
          groups.append(StoryGroup(chunks=cluster, sources=sources))

      logger.info("Deduplicated %d cluster(s) into %d story group(s)", len(clusters), len(groups))
      return groups
  ```

- **GOTCHA**: Import `StoryChunk` from `processing.embedder`, not from `ingestion.email_parser` — `StoryChunk` is defined in `embedder.py`.
- **GOTCHA**: `sources` uses `field(default_factory=list)` in the dataclass — do NOT set `sources=[]` as the default value directly (mutable default argument bug).
- **VALIDATE**: `python -c "from processing.deduplicator import deduplicate, StoryGroup; print('import OK'); print(list(StoryGroup.__dataclass_fields__.keys()))"`

---

## TESTING STRATEGY

No separate test file required. Validation uses synthetic `StoryChunk` fixtures.

### Smoke Test — Two-chunk cluster

```python
from processing.embedder import StoryChunk
from processing.deduplicator import deduplicate

chunk1 = StoryChunk(
    text="OpenAI launches GPT-5.",
    sender="TLDR AI",
    links=[{"url": "https://openai.com/gpt5", "anchor_text": "Read more"}],
)
chunk2 = StoryChunk(
    text="OpenAI releases GPT-5 today.",
    sender="The Rundown",
    links=[{"url": "https://therundown.ai/gpt5", "anchor_text": "GPT-5 is here"}],
)
groups = deduplicate([[chunk1, chunk2]])
assert len(groups) == 1
assert len(groups[0].chunks) == 2
assert len(groups[0].sources) == 2
assert groups[0].sources[0]["newsletter"] == "TLDR AI"
assert groups[0].sources[1]["newsletter"] == "The Rundown"
```

### Edge Cases

- `deduplicate([])` → `[]`
- Single-chunk cluster → one group with one source entry
- Duplicate URLs across chunks → only first URL occurrence kept
- Chunk with no links → source entry with empty url/anchor, newsletter name preserved
- Cluster larger than 5 → `logger.warning` emitted

---

## VALIDATION COMMANDS

### Level 1: Import check and StoryGroup fields

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.deduplicator import deduplicate, StoryGroup; print('import OK'); print(list(StoryGroup.__dataclass_fields__.keys()))"
```
Expected output:
```
import OK
['chunks', 'sources']
```

### Level 2: Empty input guard

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.deduplicator import deduplicate
result = deduplicate([])
print('empty input result:', result)
"
```
Expected output: `empty input result: []`

### Level 3: Two-chunk cluster smoke test

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import StoryChunk
from processing.deduplicator import deduplicate, StoryGroup

chunk1 = StoryChunk(
    text='OpenAI launches GPT-5.',
    sender='TLDR AI',
    links=[{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}],
)
chunk2 = StoryChunk(
    text='OpenAI releases GPT-5 today.',
    sender='The Rundown',
    links=[{'url': 'https://therundown.ai/gpt5', 'anchor_text': 'GPT-5 is here'}],
)
groups = deduplicate([[chunk1, chunk2]])
assert len(groups) == 1, f'Expected 1 group, got {len(groups)}'
assert len(groups[0].chunks) == 2, f'Expected 2 chunks'
assert len(groups[0].sources) == 2, f'Expected 2 sources, got {len(groups[0].sources)}'
assert groups[0].sources[0] == {'newsletter': 'TLDR AI', 'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}, f'source[0]={groups[0].sources[0]}'
assert groups[0].sources[1] == {'newsletter': 'The Rundown', 'url': 'https://therundown.ai/gpt5', 'anchor_text': 'GPT-5 is here'}, f'source[1]={groups[0].sources[1]}'
print('Two-chunk cluster test PASSED')
print('sources:', groups[0].sources)
"
```
Expected output:
```
Two-chunk cluster test PASSED
sources: [{'newsletter': 'TLDR AI', 'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}, {'newsletter': 'The Rundown', 'url': 'https://therundown.ai/gpt5', 'anchor_text': 'GPT-5 is here'}]
```

### Level 4: URL dedup + no-links chunk

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import StoryChunk
from processing.deduplicator import deduplicate

# Duplicate URL across two chunks: second occurrence should be dropped
chunk_a = StoryChunk(text='Story A.', sender='Source A', links=[{'url': 'https://same.com', 'anchor_text': 'Link'}])
chunk_b = StoryChunk(text='Story B.', sender='Source B', links=[{'url': 'https://same.com', 'anchor_text': 'Same link'}])
groups = deduplicate([[chunk_a, chunk_b]])
assert len(groups[0].sources) == 1, f'Expected 1 source after URL dedup, got {len(groups[0].sources)}'
assert groups[0].sources[0]['newsletter'] == 'Source A'
print('URL dedup test PASSED')

# Chunk with no links: should still appear in sources with empty url
chunk_no_links = StoryChunk(text='Story with no links.', sender='Linkless Newsletter', links=[])
chunk_with_link = StoryChunk(text='Story with link.', sender='Linked Newsletter', links=[{'url': 'https://example.com', 'anchor_text': 'Click here'}])
groups2 = deduplicate([[chunk_no_links, chunk_with_link]])
senders = [s['newsletter'] for s in groups2[0].sources]
assert 'Linkless Newsletter' in senders, f'Linkless newsletter missing from sources: {senders}'
no_link_src = next(s for s in groups2[0].sources if s['newsletter'] == 'Linkless Newsletter')
assert no_link_src['url'] == '', f'Expected empty url, got {no_link_src[\"url\"]}'
print('No-links chunk test PASSED')
"
```
Expected output:
```
URL dedup test PASSED
No-links chunk test PASSED
```

### Level 5: Multi-cluster and singleton passthrough

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import StoryChunk
from processing.deduplicator import deduplicate

# Three separate clusters: verify count and structure preserved
c1 = StoryChunk(text='GPT-5 launch.', sender='A', links=[{'url': 'https://a.com', 'anchor_text': 'a'}])
c2 = StoryChunk(text='Climate funding.', sender='B', links=[])
c3a = StoryChunk(text='Python 4.0 release.', sender='C', links=[{'url': 'https://c.com', 'anchor_text': 'c'}])
c3b = StoryChunk(text='Python 4.0 announced.', sender='D', links=[{'url': 'https://d.com', 'anchor_text': 'd'}])

groups = deduplicate([[c1], [c2], [c3a, c3b]])
print(f'Number of groups: {len(groups)}')
print(f'Group 0 chunks: {len(groups[0].chunks)}, sources: {len(groups[0].sources)}')
print(f'Group 1 chunks: {len(groups[1].chunks)}, sources: {len(groups[1].sources)}')
print(f'Group 2 chunks: {len(groups[2].chunks)}, sources: {len(groups[2].sources)}')
assert len(groups) == 3
assert len(groups[0].chunks) == 1
assert len(groups[1].sources) == 1 and groups[1].sources[0]['url'] == ''
assert len(groups[2].chunks) == 2 and len(groups[2].sources) == 2
print('Multi-cluster test PASSED')
"
```
Expected output:
```
Number of groups: 3
Group 0 chunks: 1, sources: 1
Group 1 chunks: 1, sources: 1
Group 2 chunks: 2, sources: 2
Multi-cluster test PASSED
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `processing/deduplicator.py` exists
- [ ] `from processing.deduplicator import deduplicate, StoryGroup` imports cleanly
- [ ] `StoryGroup` has exactly 2 fields: `chunks` and `sources`
- [ ] `deduplicate([])` returns `[]`
- [ ] Two-chunk cluster test passes with correct source attribution
- [ ] Duplicate URLs across chunks deduplicated (only first occurrence kept)
- [ ] Chunk with no links still appears in sources with empty `url` and `anchor_text`
- [ ] Multi-cluster test passes with correct group count and structure
- [ ] `StoryChunk` imported from `processing.embedder` (not from `ingestion.email_parser`)

## ROLLBACK CONSIDERATIONS

- New file only; rollback = delete `processing/deduplicator.py`
- No database changes, migrations, or config changes required

## ACCEPTANCE CRITERIA

- [ ] `deduplicate()` accepts `list[list[StoryChunk]]` and returns `list[StoryGroup]`
- [ ] `StoryGroup` has fields `chunks: list[StoryChunk]` and `sources: list[dict]`
- [ ] Each source entry has keys `"newsletter"`, `"url"`, `"anchor_text"`
- [ ] URLs deduplicated across chunks (first occurrence wins)
- [ ] Chunks with no links still contribute a source entry (empty url)
- [ ] Clusters > 5 emit a `logger.warning`
- [ ] Empty input returns `[]`
- [ ] All 5 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1: `processing/deduplicator.py` created with `StoryGroup`, `_build_sources()`, `deduplicate()`
- [ ] Level 1 validation passed
- [ ] Level 2 validation passed
- [ ] Level 3 validation passed
- [ ] Level 4 validation passed
- [ ] Level 5 validation passed

---

## NOTES

**Why `sources` carries empty-URL entries for link-free chunks:**
The AI prompt uses `chunk.sender` for newsletter attribution in the `<source newsletter="...">` tag. The `sources` list in the final API response should also include every contributing newsletter — even ones without outbound links (some newsletters summarize without linking). An empty-URL source entry preserves attribution without omitting the newsletter.

**Why chunks are passed through as-is (not merged into a single text):**
The AI client (`claude_client.py`) constructs the prompt using individual `<source newsletter="{name}">{text}</source>` blocks per chunk. Merging text at this stage would lose the newsletter attribution needed for the prompt template. `StoryGroup.chunks` is the list, not a merged string.

**Why deduplicate by URL, not by anchor text:**
Two newsletters may link to the same URL with different anchor text. URL is the canonical identifier for a web resource. Different anchor texts pointing to the same URL are the same source.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `processing/deduplicator.py` exists
  Expected output or result:
  File present at `processing/deduplicator.py` (visible in the Completed Tasks section of the execution report)

- Item to check:
  `.venv/bin/python -c "from processing.deduplicator import deduplicate, StoryGroup; print('import OK'); print(list(StoryGroup.__dataclass_fields__.keys()))"`
  Expected output or result:
  ```
  import OK
  ['chunks', 'sources']
  ```

- Item to check:
  `.venv/bin/python -c "from processing.deduplicator import deduplicate; result = deduplicate([]); print('empty input result:', result)"`
  Expected output or result:
  `empty input result: []`

- Item to check:
  Two-chunk cluster smoke test
  Expected output or result:
  ```
  Two-chunk cluster test PASSED
  sources: [{'newsletter': 'TLDR AI', 'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}, {'newsletter': 'The Rundown', 'url': 'https://therundown.ai/gpt5', 'anchor_text': 'GPT-5 is here'}]
  ```

- Item to check:
  URL dedup + no-links chunk test
  Expected output or result:
  ```
  URL dedup test PASSED
  No-links chunk test PASSED
  ```

- Item to check:
  Multi-cluster and singleton passthrough test
  Expected output or result:
  ```
  Number of groups: 3
  Group 0 chunks: 1, sources: 1
  Group 1 chunks: 1, sources: 1
  Group 2 chunks: 2, sources: 2
  Multi-cluster test PASSED
  ```

- Item to check:
  `StoryGroup` has exactly 2 fields: `chunks` and `sources`
  Expected output or result:
  Confirmed by Level 1 output: `['chunks', 'sources']`

- Item to check:
  `deduplicate([])` returns `[]`
  Expected output or result:
  Confirmed by Level 2 output: `empty input result: []`

- Item to check:
  `StoryChunk` imported from `processing.embedder` (not `ingestion.email_parser`)
  Expected output or result:
  Confirmed by Level 1 clean import with no ImportError

- Item to check:
  Duplicate URLs across chunks deduplicated (only first occurrence kept)
  Expected output or result:
  Confirmed by Level 4 `URL dedup test PASSED`

- Item to check:
  Chunk with no links still appears in sources with empty `url` and `anchor_text`
  Expected output or result:
  Confirmed by Level 4 `No-links chunk test PASSED`
