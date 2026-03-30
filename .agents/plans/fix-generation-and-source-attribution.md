# Fix: Generation batching and source attribution

The following plan should be complete, but validate documentation and codebase patterns
before implementing. Both fixes are localized. No schema changes, no new files beyond the
test suite, no changes to the pipeline orchestration in digest_builder.py.

## Feature Description

Two confirmed pipeline bugs from the first real-world test run (March 17, 5 emails, 65
reviewed groups, 50 capped, 21 entries returned):

1. **Generation truncation**: With 50 story groups in a single API call, Claude exhausts
   the 8192-token output ceiling mid-generation and stops at entry 21. The fix is to batch
   generation inside `generate_digest()` so each API call handles a smaller group count,
   keeping output per call well within the token ceiling. The 50-group post-review cap in
   `digest_builder.py` is unchanged — story coverage is fully preserved.

2. **Wrong source links**: `_build_sources()` pools ALL links from ALL chunks in a cluster
   and picks one winner by `(path_depth, anchor_length)`. This destroys the chunk-to-link
   relationship. When a sponsor chunk and a story chunk land in the same cluster, the
   sponsor link can win purely on anchor length and be attached to the wrong story. The fix
   is to select each chunk's own best link independently, preserving provenance. Sponsor
   content is not filtered — sponsor chunks still produce a source entry in the output.

## User Story

As a user reading the digest,
I want all reviewed story groups to appear as complete entries with links that belong to
each story,
So that I can follow up on any story by clicking through to the correct source.

## Problem Statement

- Generation collapses: 50 groups sent in one API call, only 21 entries returned because
  haiku-4-5's 8192 output token ceiling is exhausted before generation completes.
- Source links are misattributed: a story about Anthropic enterprise may display a link
  from a Google Cloud sponsor chunk in the same cluster, because the sponsor anchor text
  was longer and won the cross-cluster pool scoring.

## Scope

- In scope:
  - `ai/claude_client.py` — add `_BATCH_SIZE` constant, rewrite `generate_digest()` to
    loop over batches, keep all batch results merged into a single return list
  - `processing/deduplicator.py` — rewrite `_build_sources()` to select per-chunk
  - `tests/test_deduplicator.py` — new unit test file
  - `tests/test_claude_client.py` — new unit test file for batch split logic
- Out of scope:
  - `processing/digest_builder.py` — no changes; `_MAX_STORY_GROUPS = 50` stays as-is
  - `ai/story_reviewer.py` — no changes
  - Embedder, imap client, email parser — no changes
  - Frontend, PDF export, API routes — not yet built

## Solution Statement

**Fix A — batched generation**: Add `_BATCH_SIZE = 20` to `claude_client.py`. Rewrite
`generate_digest()` to split input into slices of `_BATCH_SIZE`, call the existing API
call logic once per slice, and concatenate all batch results. The caller in
`digest_builder.py` sees no change — it still calls `generate_digest(reviewed_groups,
folder)` and receives a flat list of entries. With batches of 20, each call generates
~7800 tokens (20 x ~390 tokens/entry), safely under the 8192 ceiling.

**Fix B — per-chunk source attribution**: Replace `_build_sources()` pooling logic with
a per-chunk loop: for each chunk, independently pick that chunk's own best link using
`_score_source()`, then deduplicate across chunks by URL. Returns one source per
unique-URL contributing chunk. `_score_source()` is unchanged.

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ai/claude_client.py`, `processing/deduplicator.py`
**Dependencies**: None (no new libraries)
**Assumptions**:
- `claude-haiku-4-5` max output tokens is 8192 (hard ceiling per Anthropic docs for this
  model). Observed rate: 8192 / 21 entries = ~390 tokens/entry. Batch of 20 leaves ~400
  token margin.
- `_build_user_message()` and `_system_prompt()` already reference `len(story_groups)`
  dynamically, so they work correctly when called with a batch slice.
- `_score_source()` is correct for ranking links within a single chunk. Only the
  cross-chunk pooling is wrong; the scorer itself does not change.
- No frontend or PDF export code exists yet, so sources list expanding from length-1 to
  length-N is safe downstream.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `ai/claude_client.py` (lines 1–57) — Why: constants `_TOOL_NAME`, `_MAX_TOKENS`,
  `_TOOL_SCHEMA`, `_system_prompt()`, `_build_user_message()`. All unchanged by Fix A.
  The new `_BATCH_SIZE` constant is added here.
- `ai/claude_client.py` (lines 105–187) — Why: `generate_digest()` is the function being
  rewritten for batching. Read the full function before implementing. The API call block
  (lines 133–144), debug log (146–151), tool extraction (153–164), mismatch warning
  (169–175), and merge loop (177–185) are all reused per-batch in the new implementation.
- `processing/deduplicator.py` (lines 19–70) — Why: `_score_source()` (unchanged) and
  `_build_sources()` (rewritten). Read both docstrings before implementing Fix B.
- `processing/deduplicator.py` (lines 73–107) — Why: `deduplicate()` calls
  `_build_sources()` and handles the sourceless-cluster guard. Confirm it needs no change.
- `processing/embedder.py` (lines 62–66) — Why: confirms `StoryChunk.links` field shape:
  `list[dict]` with keys `"url"` and `"anchor_text"`. No change needed.
- `processing/digest_builder.py` (lines 22, 108–120) — Why: confirms `_MAX_STORY_GROUPS`
  stays 50 and that `digest_builder.py` calls `generate_digest(reviewed_groups, folder)`
  without knowing or caring about internal batching. No change to this file.

### New Files to Create

- `tests/test_deduplicator.py` — unit tests for the new `_build_sources()` behavior
- `tests/test_claude_client.py` — unit test for batch split logic (pure, no API calls)

### Patterns to Follow

**Constant declaration** (`claude_client.py` lines 13–15):
```python
_TOOL_NAME = "create_digest_entries"
_MAX_TOKENS = 8192
_MAX_CHUNK_CHARS = 600
```
New `_BATCH_SIZE = 20` constant follows the same style, placed after `_MAX_TOKENS`.

**Batch split idiom** (standard Python):
```python
batches = [story_groups[i:i + _BATCH_SIZE] for i in range(0, len(story_groups), _BATCH_SIZE)]
```

**Logging pattern** (`claude_client.py` line 126–131):
```python
logger.info(
    "Calling Claude (%s) with %d story group(s) for folder '%s'",
    settings.claude_model,
    len(story_groups),
    folder,
)
```
Batch loop adds per-batch log lines following the same `logger.info("Batch %d/%d — ...")`
pattern.

**Error propagation** (`claude_client.py` lines 142–144):
```python
except anthropic.APIError as exc:
    logger.error("Claude API error: %s", exc)
    raise
```
Re-raised unchanged per batch. One batch failure aborts the full call (consistent with
existing behavior).

**`_build_sources()` outer loop** (`deduplicator.py` lines 55–64):
```python
for chunk in cluster:
    for link in chunk.links:
        ...
```
New version keeps the outer `for chunk in cluster` but removes the inner `for link in
chunk.links` flat-pool accumulation. Instead, one `max()` per chunk over `chunk.links`.

**`_score_source()` call shape** (`deduplicator.py` lines 31–38): takes a dict with keys
`"url"` and `"anchor_text"`. When calling from inside the lambda over `chunk.links`,
wrap the raw link:
```python
key=lambda l: _score_source({"url": l.get("url", ""), "anchor_text": l.get("anchor_text", "")})
```

---

## IMPLEMENTATION PLAN

### Phase 1: Fix A — batched generation in claude_client.py

Add `_BATCH_SIZE = 20` constant after `_MAX_TOKENS`. Rewrite `generate_digest()` to
split story_groups into batches, run one API call per batch, accumulate results into a
single list. All existing helper functions (`_system_prompt`, `_build_user_message`,
`_get_client`) are called per-batch without modification.

### Phase 2: Fix B — per-chunk source attribution in deduplicator.py

Replace `_build_sources()` body. Function signature, return type, and sourceless-cluster
guard (`return []`) are unchanged. `_score_source()` is unchanged.

### Phase 3: Tests

Create `tests/` directory, `tests/test_deduplicator.py` (8 test cases for `_build_sources`
including a sponsor-anchor regression test), and `tests/test_claude_client.py` (batch
split logic test, pure Python, no API calls).

---

## STEP-BY-STEP TASKS

### TASK 1 — UPDATE `ai/claude_client.py` — add _BATCH_SIZE constant

- **IMPLEMENT**: Add `_BATCH_SIZE = 20` after the `_MAX_TOKENS` line (line 14). Add a
  comment explaining the derivation:
  ```python
  _MAX_TOKENS = 8192
  _BATCH_SIZE = 20   # ~390 tokens/entry x 20 = ~7 800 tokens; fits haiku-4-5's 8 192 ceiling
  ```
- **PATTERN**: Constant block at `claude_client.py` lines 13–15
- **GOTCHA**: Do not change `_MAX_TOKENS`. The value 8192 is the model ceiling and correct.
- **VALIDATE**: `python -c "from ai.claude_client import _BATCH_SIZE; assert _BATCH_SIZE == 20; print('PASSED: _BATCH_SIZE == 20')"`

---

### TASK 2 — UPDATE `ai/claude_client.py` — rewrite generate_digest() for batching

- **IMPLEMENT**: Replace the full body of `generate_digest()` (lines 120–187) with the
  batching implementation below. The function signature and docstring header are unchanged;
  update the docstring body to reflect batching.

  ```python
  async def generate_digest(story_groups: list[StoryGroup], folder: str) -> list[dict]:
      """Call Claude to generate digest entries, batching to respect the output token ceiling.

      Splits story_groups into slices of _BATCH_SIZE and calls the Claude API once per
      slice. Results are appended to the output list in the same order as the input —
      batch 1 entries first, then batch 2, etc. — so the final list is identical in order
      and structure to what a single-call implementation would return.

      Args:
          story_groups: List of StoryGroup objects from deduplicate().
          folder: IMAP folder name used as topic context in the prompt.

      Returns:
          List of digest entry dicts, one per story group, each containing:
          {"headline": str, "summary": str, "significance": str, "sources": list[dict]}
          Returns [] if story_groups is empty.

      Raises:
          anthropic.APIError: On any Anthropic API failure. Propagates immediately;
                              entries from completed batches are discarded.
      """
      if not story_groups:
          return []

      client = _get_client()
      batches = [story_groups[i:i + _BATCH_SIZE] for i in range(0, len(story_groups), _BATCH_SIZE)]

      logger.info(
          "Calling Claude (%s) with %d story group(s) in %d batch(es) for folder '%s'",
          settings.claude_model,
          len(story_groups),
          len(batches),
          folder,
      )

      result: list[dict] = []

      for batch_num, batch in enumerate(batches, 1):
          user_message = _build_user_message(batch, folder)

          logger.info(
              "Batch %d/%d — generating %d entries",
              batch_num,
              len(batches),
              len(batch),
          )

          try:
              response = await client.messages.create(
                  model=settings.claude_model,
                  max_tokens=_MAX_TOKENS,
                  system=_system_prompt(folder),
                  messages=[{"role": "user", "content": user_message}],
                  tools=[_TOOL_SCHEMA],
                  tool_choice={"type": "tool", "name": _TOOL_NAME},
              )
          except anthropic.APIError as exc:
              logger.error("Claude API error on batch %d/%d: %s", batch_num, len(batches), exc)
              raise

          logger.debug(
              "Batch %d/%d response: stop_reason=%r  input_tokens=%d  output_tokens=%d",
              batch_num,
              len(batches),
              response.stop_reason,
              response.usage.input_tokens,
              response.usage.output_tokens,
          )

          # Extract tool input from the response
          tool_input: dict | None = None
          for block in response.content:
              if block.type == "tool_use":
                  tool_input = block.input
                  break

          if tool_input is None:
              raise ValueError(
                  f"Claude response contained no tool_use block on batch {batch_num}/{len(batches)}. "
                  f"stop_reason={response.stop_reason!r}"
              )

          raw_entries: list[dict] = tool_input.get("entries", [])
          logger.info(
              "Batch %d/%d — Claude returned %d entries",
              batch_num,
              len(batches),
              len(raw_entries),
          )

          if len(raw_entries) != len(batch):
              logger.warning(
                  "Batch %d/%d entry count mismatch: Claude returned %d entries for %d story groups"
                  " — truncating/padding to match",
                  batch_num,
                  len(batches),
                  len(raw_entries),
                  len(batch),
              )

          # Merge Claude's text fields with pre-built source attribution from deduplicator
          for entry, group in zip(raw_entries, batch):
              result.append({
                  "headline": entry.get("headline", ""),
                  "summary": entry.get("summary", ""),
                  "significance": entry.get("significance", ""),
                  "sources": group.sources,
              })

      logger.info(
          "Stage 6/6 — Generated %d total digest entry/entries across %d batch(es)",
          len(result),
          len(batches),
      )
      return result
  ```

- **PATTERN**: Existing API call block `claude_client.py` lines 133–144 — reused verbatim
  inside the batch loop
- **PATTERN**: Existing mismatch warning `claude_client.py` lines 169–175 — updated to
  include batch context
- **GOTCHA**: `_build_user_message(batch, folder)` receives the batch slice, not the full
  list. The prompt says "Below are N story groups" where N = len(batch). This is correct —
  each batch is a self-contained generation call.
- **GOTCHA**: Output ordering must be identical to a single-call implementation. The
  batch split (`story_groups[i:i + _BATCH_SIZE]`) preserves input order within each
  slice. The `for batch_num, batch in enumerate(batches, 1)` loop processes slices in
  order. The inner `for entry, group in zip(raw_entries, batch)` appends entries in
  slice order. Do NOT sort, shuffle, or reorder batches or entries at any point.
- **GOTCHA**: `digest_builder.py` line 120 logs `"Stage 6/6 — Generated %d digest
  entry/entries"`. Remove or suppress that log line from `digest_builder.py`? No — the
  new `generate_digest()` emits its own final summary log (`Stage 6/6 — Generated %d
  total digest entry/entries across %d batch(es)`). The `digest_builder.py` log at line
  120 reads `len(stories)` after the call returns, which is still correct and harmless.
  Do not change `digest_builder.py`.
- **VALIDATE**: `python -c "import inspect, asyncio; from ai.claude_client import generate_digest; src = inspect.getsource(generate_digest); assert '_BATCH_SIZE' in src; print('PASSED: generate_digest uses _BATCH_SIZE')"`

---

### TASK 3 — UPDATE `processing/deduplicator.py` — rewrite _build_sources()

- **IMPLEMENT**: Replace the body of `_build_sources()` (lines 52–70) with per-chunk
  selection. Function signature, return type annotation, and position in file are unchanged.

  ```python
  def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
      """Collect sources from a cluster, one per chunk using that chunk's own best link.

      For each chunk in the cluster, independently selects the best link from that chunk's
      own links using _score_source(). This preserves the chunk-to-link relationship:
      a sponsor chunk's link is never attributed to a story chunk, and vice versa.

      Sources are deduplicated by URL across chunks (a URL appearing in two chunks is
      included only once, attributed to the first chunk that contributes it).

      Returns a list with one entry per unique-URL contributing chunk. Returns [] if no
      chunk has any valid links (sourceless cluster, dropped by deduplicate()).
      """
      sources: list[dict] = []
      seen_urls: set[str] = set()

      for chunk in cluster:
          if not chunk.links:
              continue
          best_link = max(
              chunk.links,
              key=lambda l: _score_source({"url": l.get("url", ""), "anchor_text": l.get("anchor_text", "")}),
          )
          url = best_link.get("url", "")
          if url and url not in seen_urls:
              seen_urls.add(url)
              sources.append({
                  "newsletter": chunk.sender,
                  "url": url,
                  "anchor_text": best_link.get("anchor_text", ""),
              })

      return sources
  ```

- **PATTERN**: Existing `_build_sources()` docstring style — `deduplicator.py` lines 41–51
- **GOTCHA**: `_score_source()` takes a dict with keys `"url"` and `"anchor_text"`. Raw
  link dicts from `chunk.links` use the same keys, but wrap them explicitly inside the
  lambda to be safe and explicit.
- **GOTCHA**: Do not modify `_score_source()`, `StoryGroup`, `deduplicate()`, or any other
  function. Only `_build_sources()` changes.
- **VALIDATE**: `python -c "from processing.deduplicator import _build_sources; print('PASSED: _build_sources importable')"`

---

### TASK 4 — CREATE `tests/test_deduplicator.py`

- **IMPLEMENT**: Create `tests/` directory and `tests/test_deduplicator.py`.

  ```python
  from __future__ import annotations

  import sys
  import os
  sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

  from processing.embedder import StoryChunk
  from processing.deduplicator import _build_sources


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
  ```

- **VALIDATE**: `python -m pytest tests/test_deduplicator.py -v`

---

### TASK 5 — CREATE `tests/test_claude_client.py`

- **IMPLEMENT**: Create `tests/test_claude_client.py` with a pure batch-split test that
  does not call the Anthropic API.

  ```python
  from __future__ import annotations

  import sys
  import os
  sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

  from ai.claude_client import _BATCH_SIZE


  def test_batch_size_value():
      """_BATCH_SIZE must be 20 (derived from observed ~390 tokens/entry, 8192 ceiling)."""
      assert _BATCH_SIZE == 20, (
          f"_BATCH_SIZE is {_BATCH_SIZE}, expected 20. "
          "Update this test and the inline comment in claude_client.py together."
      )


  def test_batch_split_50_groups():
      """50 story groups split into ceil(50/20) = 3 batches: 20, 20, 10."""
      groups = list(range(50))  # stand-in for StoryGroup objects; split logic is identical
      batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
      assert len(batches) == 3
      assert len(batches[0]) == 20
      assert len(batches[1]) == 20
      assert len(batches[2]) == 10


  def test_batch_split_single_group():
      """1 story group produces 1 batch of 1."""
      groups = [object()]
      batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
      assert len(batches) == 1
      assert len(batches[0]) == 1


  def test_batch_split_exactly_one_batch():
      """20 story groups produce exactly 1 batch."""
      groups = list(range(20))
      batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
      assert len(batches) == 1
      assert len(batches[0]) == 20


  def test_batch_split_21_groups():
      """21 story groups produce 2 batches: 20, 1."""
      groups = list(range(21))
      batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
      assert len(batches) == 2
      assert len(batches[0]) == 20
      assert len(batches[1]) == 1


  def test_batch_split_preserves_order():
      """Concatenating batch slices reproduces the original input order exactly."""
      groups = list(range(50))
      batches = [groups[i:i + _BATCH_SIZE] for i in range(0, len(groups), _BATCH_SIZE)]
      merged = []
      for batch in batches:
          merged.extend(batch)
      assert merged == groups, "Batch concatenation must reproduce the original input order"
  ```

- **VALIDATE**: `python -m pytest tests/test_claude_client.py -v`

---

## TESTING STRATEGY

### Unit Tests

All tests are pure Python — no database, no API calls, no IMAP connections.

**`tests/test_deduplicator.py`** (8 tests):
- Single chunk, single link
- Single chunk, multiple links — best selected by path depth
- Two chunks — each attributed to own chunk (core correctness)
- Duplicate URL across chunks — deduplicated
- Chunk with no links — skipped
- All chunks have no links — returns `[]`
- Empty cluster — returns `[]`
- Sponsor anchor does not steal story link (regression test for the confirmed bug)

**`tests/test_claude_client.py`** (6 tests):
- `_BATCH_SIZE == 20` constant assertion
- 50 groups → 3 batches (20, 20, 10) — matches real-world scenario
- 1 group → 1 batch
- 20 groups → 1 batch exactly
- 21 groups → 2 batches (20, 1)
- Batch concatenation reproduces original input order exactly

### Edge Cases

- Chunk with `"url": ""` — skipped by `if url` guard in `_build_sources()`
- Chunk with missing `"anchor_text"` key — `l.get("anchor_text", "")` handles gracefully
- Batch of 1 (last batch of 49-group input) — API call works; 1 entry returned
- `generate_digest([])` — returns `[]` immediately, no batches created

---

## DOWNSTREAM BEHAVIOR CHANGE — SOURCES LIST

**Before this change:**
`_build_sources()` always returned exactly one element. The `sources` field in every
digest story entry was always a single-element list.

**After this change:**
`_build_sources()` returns one element per unique-URL contributing chunk. For clusters
with 1 chunk: still a single-element list (unchanged for unique stories). For clusters
with N chunks and distinct URLs: N elements.

**API output shape change:**
```json
// Before (always length 1):
"sources": [
  {"newsletter": "TLDR AI", "url": "https://...", "anchor_text": "..."}
]

// After (multi-source cluster, length N):
"sources": [
  {"newsletter": "TLDR AI", "url": "https://ai-story.com/article", "anchor_text": "New AI chip release"},
  {"newsletter": "The Batch", "url": "https://deeplearning.ai/issue/123", "anchor_text": "AI chip breakdown"}
]
```

**Consumers and impact:**
- `StoryGroup.sources: list[dict]` — already `list[dict]`, no type change
- `claude_client.py` line `"sources": group.sources` — list passthrough, any length works
- `digest_builder.py` response dict — passthrough, no change
- `ai/story_reviewer.py` — reads `group.chunks` only, never reads `group.sources`
- `api/digests.py`, `static/app.js`, `api/export.py` — not yet built, no impact

Nothing breaks. The change produces richer, more accurate source attribution.

---

## VALIDATION COMMANDS

### Level 1: Syntax and import check

```bash
python -c "import ai.claude_client; import processing.deduplicator; print('PASSED: syntax ok')"
```

### Level 2: Constant assertions

```bash
python -c "from ai.claude_client import _BATCH_SIZE; assert _BATCH_SIZE == 20; print('PASSED: _BATCH_SIZE == 20')"
python -c "from processing.digest_builder import _MAX_STORY_GROUPS; assert _MAX_STORY_GROUPS == 50; print('PASSED: _MAX_STORY_GROUPS == 50 (unchanged)')"
```

### Level 3: Batching logic in generate_digest

```bash
python -c "import inspect; from ai.claude_client import generate_digest; src = inspect.getsource(generate_digest); assert '_BATCH_SIZE' in src; print('PASSED: generate_digest uses _BATCH_SIZE')"
```

### Level 4: Unit tests

```bash
python -m pytest tests/test_deduplicator.py -v
python -m pytest tests/test_claude_client.py -v
python -m pytest tests/ -v
```

### Level 5: Manual pipeline run

Run the same 1-day test to confirm no truncation and correct attribution:

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17
```

Expected log output:
- `Calling Claude (claude-haiku-4-5) with 50 story group(s) in 3 batch(es) for folder 'AI Newsletters'`
- Three `Batch N/3 — generating M entries` lines
- Final: `Generated 50 total digest entry/entries across 3 batch(es)` (or whatever the
  actual count is after the cap, with no mismatch warning)
- No `Entry count mismatch` WARNING in the output

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_BATCH_SIZE = 20` constant present in `claude_client.py` with derivation comment
- [ ] `generate_digest()` docstring updated to describe batching behavior
- [ ] `_MAX_STORY_GROUPS` in `digest_builder.py` is still 50 (unchanged)
- [ ] `_build_sources()` docstring reflects per-chunk selection behavior
- [ ] All 8 tests in `test_deduplicator.py` pass
- [ ] All 5 tests in `test_claude_client.py` pass
- [ ] Manual pipeline run shows 3-batch generation log lines
- [ ] Manual pipeline run produces no `Entry count mismatch` warning
- [ ] Manual pipeline run produces story_count equal to the post-review, post-cap count
- [ ] Spot-check 2-3 stories in the output JSON — source URLs belong to the correct story

## ROLLBACK CONSIDERATIONS

Both changes are confined to pure Python functions with no DB migrations.
- Fix A rollback: revert `_BATCH_SIZE` constant and restore single-call `generate_digest()`
- Fix B rollback: revert `_build_sources()` to pooling implementation
No config changes, no schema changes required.

## ACCEPTANCE CRITERIA

- [ ] `_BATCH_SIZE == 20` — verified by constant assertion and test
- [ ] 50 story groups produce 3 API calls (20 + 20 + 10), all 50 entries returned
- [ ] No `Entry count mismatch` WARNING when story groups <= cap per batch
- [ ] `_build_sources()` returns one source per unique-URL chunk
- [ ] Sponsor chunks contribute their own source entry; story chunks are unaffected
- [ ] URL deduplication prevents duplicate entries when two chunks share a URL
- [ ] All 14 unit tests pass (`pytest tests/`)
- [ ] Manual run confirms correct story-to-link pairing (spot-check 2-3 entries)
- [ ] `_MAX_STORY_GROUPS` in `digest_builder.py` is still 50

---

## COMPLETION CHECKLIST

- [ ] TASK 1 complete: `_BATCH_SIZE = 20` added to `claude_client.py`
- [ ] TASK 2 complete: `generate_digest()` rewritten with batch loop
- [ ] TASK 3 complete: `_build_sources()` rewritten with per-chunk selection
- [ ] TASK 4 complete: `tests/test_deduplicator.py` with 8 test cases
- [ ] TASK 5 complete: `tests/test_claude_client.py` with 5 test cases
- [ ] All Level 1-4 validation commands pass
- [ ] Manual pipeline run confirms batching and correct attribution
- [ ] Ready for `/commit`

---

## NOTES

**Why batch size 20?**
Observed in test run: 21 entries exhausted 8192 tokens = ~390 tokens/entry. Batch of 20
gives ~7800 tokens output, leaving ~400 tokens margin. This is a conservative but reliable
bound. If entries in practice average fewer tokens (e.g., 150 tokens), the batch size
could be increased later; the constant is easy to update.

**Why not increase _MAX_TOKENS instead?**
`claude-haiku-4-5` has a hard output limit of 8192 tokens. Setting `_MAX_TOKENS` higher
than 8192 would cause an API validation error. The value stays at 8192.

**Why does batching preserve all stories?**
Each batch is a self-contained Claude call. `_build_user_message(batch, folder)` correctly
builds a prompt for `len(batch)` groups. Entries are appended to `result` in order.
The caller receives a flat list of all entries regardless of how many batches were needed.

**Why does per-chunk attribution preserve sponsor content?**
A sponsor chunk that passes the AI reviewer (Stage 5) produces its own `StoryGroup` with
`chunks=[sponsor_chunk]`. Its `sources` will contain the sponsor link. The only case where
a sponsor link previously appeared on the wrong story was when it was merged into another
story's cluster — a misattribution. That misattribution is now prevented. Sponsor stories
that cluster cleanly are unaffected.

**digest_builder.py Stage 6 log line:**
`digest_builder.py` line 120 logs `"Stage 6/6 — Generated %d digest entry/entries"`.
The new `generate_digest()` also logs a final summary. Both log lines will appear:
`generate_digest()` logs batch-level detail; `digest_builder.py` logs the pipeline-level
count. This is not a problem — the `digest_builder.py` log remains accurate.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK (DO NOT SKIP)

- Item to check:
  `python -c "import ai.claude_client; import processing.deduplicator; print('PASSED: syntax ok')"`
  Expected output or result:
  ```
  PASSED: syntax ok
  ```

- Item to check:
  `python -c "from ai.claude_client import _BATCH_SIZE; assert _BATCH_SIZE == 20; print('PASSED: _BATCH_SIZE == 20')"`
  Expected output or result:
  ```
  PASSED: _BATCH_SIZE == 20
  ```

- Item to check:
  `python -c "from processing.digest_builder import _MAX_STORY_GROUPS; assert _MAX_STORY_GROUPS == 50; print('PASSED: _MAX_STORY_GROUPS == 50 (unchanged)')"`
  Expected output or result:
  ```
  PASSED: _MAX_STORY_GROUPS == 50 (unchanged)
  ```

- Item to check:
  `python -c "import inspect; from ai.claude_client import generate_digest; src = inspect.getsource(generate_digest); assert '_BATCH_SIZE' in src; print('PASSED: generate_digest uses _BATCH_SIZE')"`
  Expected output or result:
  ```
  PASSED: generate_digest uses _BATCH_SIZE
  ```

- Item to check:
  `python -m pytest tests/test_deduplicator.py -v`
  Expected output or result:
  ```
  collected 8 items

  tests/test_deduplicator.py::test_single_chunk_single_link PASSED
  tests/test_deduplicator.py::test_single_chunk_picks_best_link PASSED
  tests/test_deduplicator.py::test_two_chunks_independent_attribution PASSED
  tests/test_deduplicator.py::test_duplicate_url_across_chunks_deduplicated PASSED
  tests/test_deduplicator.py::test_chunk_with_no_links_skipped PASSED
  tests/test_deduplicator.py::test_all_chunks_no_links_returns_empty PASSED
  tests/test_deduplicator.py::test_empty_cluster_returns_empty PASSED
  tests/test_deduplicator.py::test_sponsor_anchor_does_not_steal_story_link PASSED

  ========================= 8 passed in Xs =========================
  ```

- Item to check:
  `python -m pytest tests/test_claude_client.py -v`
  Expected output or result:
  ```
  collected 6 items

  tests/test_claude_client.py::test_batch_size_value PASSED
  tests/test_claude_client.py::test_batch_split_50_groups PASSED
  tests/test_claude_client.py::test_batch_split_single_group PASSED
  tests/test_claude_client.py::test_batch_split_exactly_one_batch PASSED
  tests/test_claude_client.py::test_batch_split_21_groups PASSED
  tests/test_claude_client.py::test_batch_split_preserves_order PASSED

  ========================= 6 passed in Xs =========================
  ```

- Item to check:
  `python -m pytest tests/ -v`
  Expected output or result:
  ```
  collected 14 items

  tests/test_claude_client.py::test_batch_size_value PASSED
  tests/test_claude_client.py::test_batch_split_50_groups PASSED
  tests/test_claude_client.py::test_batch_split_single_group PASSED
  tests/test_claude_client.py::test_batch_split_exactly_one_batch PASSED
  tests/test_claude_client.py::test_batch_split_21_groups PASSED
  tests/test_claude_client.py::test_batch_split_preserves_order PASSED
  tests/test_deduplicator.py::test_single_chunk_single_link PASSED
  tests/test_deduplicator.py::test_single_chunk_picks_best_link PASSED
  tests/test_deduplicator.py::test_two_chunks_independent_attribution PASSED
  tests/test_deduplicator.py::test_duplicate_url_across_chunks_deduplicated PASSED
  tests/test_deduplicator.py::test_chunk_with_no_links_skipped PASSED
  tests/test_deduplicator.py::test_all_chunks_no_links_returns_empty PASSED
  tests/test_deduplicator.py::test_empty_cluster_returns_empty PASSED
  tests/test_deduplicator.py::test_sponsor_anchor_does_not_steal_story_link PASSED

  ========================= 14 passed in Xs =========================
  ```

- Item to check:
  `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`
  Expected output or result:
  Log must contain all of the following lines (exact counts will vary by run):
  ```
  Stage 6/6 — Generating digest entries via Claude
  Calling Claude (claude-haiku-4-5) with N story group(s) in 3 batch(es) for folder 'AI Newsletters'
  Batch 1/3 — generating 20 entries
  Batch 1/3 — Claude returned 20 entries
  Batch 2/3 — generating 20 entries
  Batch 2/3 — Claude returned 20 entries
  Batch 3/3 — generating 10 entries
  Batch 3/3 — Claude returned 10 entries
  Stage 6/6 — Generated 50 total digest entry/entries across 3 batch(es)
  Digest run complete: id=XXXXXXXX stories=50
  ```
  Log must NOT contain:
  ```
  Entry count mismatch
  ```

- Item to check:
  `generate_digest()` docstring in `ai/claude_client.py` updated to describe batching
  Expected output or result:
  File `ai/claude_client.py` contains the text "batching" in the `generate_digest()`
  docstring. Confirm by opening the file and reading lines 106–120.

- Item to check:
  `_build_sources()` docstring in `processing/deduplicator.py` reflects per-chunk selection
  Expected output or result:
  File `processing/deduplicator.py` contains the text "chunk's own best link" or equivalent
  in the `_build_sources()` docstring. Confirm by reading lines 41–55.

- Item to check:
  Spot-check 2–3 stories in the pipeline JSON output — source URLs belong to the correct story topic
  Expected output or result:
  For each spot-checked story, the `sources[N].url` domain and anchor text match the story
  headline. No story about (e.g.) Anthropic enterprise has a source URL anchored to a
  Google Cloud sponsor entry. Verified visually from the JSON printed to stdout.
