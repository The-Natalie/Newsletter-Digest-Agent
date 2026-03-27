# Feature: source-selection — Select Single Best Source Per Story Group

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to the exact shape of `StoryGroup.sources` (list of dicts with keys `newsletter`, `url`, `anchor_text`) and the current `_build_sources()` logic before editing.

## Feature Description

Each story group currently carries all source links collected from every contributing section across every newsletter. A story covered by 3 newsletters each with 2 links produces 6 source entries. This makes the output noisy and harder to read. This plan adds a scoring function that selects the single best source link from all candidates, producing exactly 1 source per story group.

## User Story

As the pipeline,
I want each story to have exactly one high-quality, representative source link selected from all candidate links attached to that story,
So that the digest output is clean, focused, and each story clearly points to the most relevant article.

## Problem Statement

`_build_sources()` in `deduplicator.py` collects every non-duplicate link from all chunks in a cluster into `StoryGroup.sources`. This list is passed directly to the final `story["sources"]` field in the digest JSON. Stories frequently have 3–8 sources, many pointing to the same underlying article through different newsletters' tracking URLs (already normalized in Loop 2) or listing multiple links from one email (now section-scoped per Loop 3). The reader sees multiple sources where one would be clearer and more authoritative.

## Scope

- In scope: `processing/deduplicator.py` — add `_score_source()`, modify `_build_sources()` to return a single best source
- Out of scope: `ingestion/email_parser.py` (Loops 1–3 — do not touch), `processing/embedder.py` (clustering — do not touch), `ai/claude_client.py` (Claude prompt/output format — do not touch), `processing/digest_builder.py` (pipeline orchestration — no change needed)

## Solution Statement

1. Add `from urllib.parse import urlparse` to `deduplicator.py` (no new dependency — stdlib, already used in `email_parser.py`).
2. Add `_score_source(source: dict) -> tuple[int, int]` — scores a source link by `(path_depth, anchor_length)`. Both dimensions are higher-is-better: a deeper URL path signals a specific article page, and longer anchor text signals a more descriptive (and therefore better) link label.
3. Modify `_build_sources()` to collect all candidate sources into `candidates`, then return `[max(candidates, key=_score_source)]` — a single-element list preserving the existing `list[dict]` return type and downstream API shape.

## Feature Metadata

**Feature Type**: Enhancement
**Estimated Complexity**: Low
**Primary Systems Affected**: `processing/deduplicator.py`
**Dependencies**: `urllib.parse.urlparse` (stdlib — no new install)
**Assumptions**: Path depth is a reliable proxy for "article-specific" vs "homepage/landing page." Longer anchor text (among already-filtered, non-boilerplate anchors) is a reliable proxy for more descriptive quality. Both heuristics are lightweight, deterministic, and require no external calls.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `processing/deduplicator.py` (lines 1–7) — current imports. Add `from urllib.parse import urlparse` here.
- `processing/deduplicator.py` (lines 11–15) — `StoryGroup` dataclass. `sources` field shape: `list[dict]` where each dict has `{"newsletter": str, "url": str, "anchor_text": str}`. Return type does NOT change — still `list[dict]`, just always length 1.
- `processing/deduplicator.py` (lines 18–34) — `_build_sources()`. This is the only function that changes. Current logic: iterate all chunks → all links → deduplicate by URL → return full list. New logic: same collection, then `max(candidates, key=_score_source)` → return `[best]`.
- `ai/claude_client.py` (lines 191–198) — `generate_digest()` result-building loop. Reads `group.sources` directly — no change needed since shape stays `list[dict]`.
- `processing/digest_builder.py` (lines 94–102) — response dict construction. `"sources": stories` → `"sources"` comes from `generate_digest()` output — no change needed.

### New Files to Create

None. All changes in `processing/deduplicator.py`.

### Patterns to Follow

**urlparse import pattern** (email_parser.py line 10):
```python
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
```
Mirror with just `urlparse` in deduplicator (only need the parser, not reconstructors).

**Private scoring helper before the function that uses it** (mirrors `_normalize_url()` before `_is_boilerplate_url()` in email_parser.py):
```python
def _score_source(source: dict) -> tuple[int, int]:
    ...

def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
    ...
    best = max(candidates, key=_score_source)
    return [best]
```

**Defensive try/except for URL parsing** (mirrors `_is_boilerplate_url()` in email_parser.py):
```python
try:
    path = urlparse(url).path.rstrip("/")
    path_depth = len([s for s in path.split("/") if s])
except Exception:
    path_depth = 0
```

**Logging pattern** (deduplicator.py line 8):
```python
logger = logging.getLogger(__name__)
```
No new logger needed. `_score_source()` is a hot-path helper — do NOT log inside it.

---

## STEP-BY-STEP TASKS

### TASK 1: ADD `urlparse` import — `processing/deduplicator.py`

After the existing `from dataclasses import dataclass, field` import (line 4), add:

```python
from urllib.parse import urlparse
```

- **GOTCHA**: Do NOT add to requirements.txt — stdlib.
- **VALIDATE**: `python -c "from processing.deduplicator import deduplicate; print('import OK')"`

---

### TASK 2: ADD `_score_source()` function — `processing/deduplicator.py`

Add immediately before `_build_sources()` (currently line 18):

```python
def _score_source(source: dict) -> tuple[int, int]:
    """Score a source link for quality selection. Higher tuple = better source.

    Scoring dimensions (both higher-is-better):
    - path_depth: number of non-empty path segments in the URL.
      Deeper paths indicate specific article/content pages vs. homepages.
      e.g. /blog/2026/gpt-5-release → depth 3; https://openai.com/ → depth 0
    - anchor_length: character length of the anchor text.
      Among already-filtered (non-boilerplate) anchors, longer is more descriptive.

    On URL parse error, path_depth defaults to 0 (anchor_length still used as tiebreaker).
    """
    url = source.get("url", "")
    anchor = source.get("anchor_text", "")
    try:
        path = urlparse(url).path.rstrip("/")
        path_depth = len([s for s in path.split("/") if s])
    except Exception:
        path_depth = 0
    return (path_depth, len(anchor))
```

- **VALIDATE**: See Level 2 validation commands.

---

### TASK 3: UPDATE `_build_sources()` — `processing/deduplicator.py`

Replace the current `_build_sources()` body:

**Current:**
```python
def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
    """Build deduplicated source list from all chunks in a cluster."""
    sources = []
    seen_urls: set[str] = set()

    for chunk in cluster:
        for link in chunk.links:
            url = link.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "newsletter": chunk.sender,
                    "url": url,
                    "anchor_text": link.get("anchor_text", ""),
                })

    return sources
```

**Replace with:**
```python
def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
    """Collect all source links from a cluster and return the single best one.

    Candidates are deduplicated by URL (since Loop 2 already normalises URLs,
    exact-match dedup here is sufficient). The best candidate is selected by
    _score_source(): prefer deeper URL paths (article-specific > homepage),
    then longer anchor text (more descriptive > generic).

    Returns a single-element list to preserve the list[dict] return type and
    downstream API shape. Returns [] if no valid links exist (sourceless cluster).
    """
    candidates: list[dict] = []
    seen_urls: set[str] = set()

    for chunk in cluster:
        for link in chunk.links:
            url = link.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                candidates.append({
                    "newsletter": chunk.sender,
                    "url": url,
                    "anchor_text": link.get("anchor_text", ""),
                })

    if not candidates:
        return []

    best = max(candidates, key=_score_source)
    return [best]
```

- **IMPACT**: `StoryGroup.sources` is now always length 0 (sourceless, dropped) or length 1 (selected best link). Downstream `story["sources"]` is always a single-element list.
- **GOTCHA**: Return type stays `list[dict]` — no API breakage. Downstream code in `claude_client.py` (line 197: `"sources": group.sources`) passes the list through unchanged.
- **VALIDATE**: See Level 3 validation commands.

---

## VALIDATION COMMANDS

### Level 1: Import check

```bash
python -c "
from processing.deduplicator import deduplicate, _build_sources, _score_source
print('Level 1 PASSED: all symbols importable')
"
```

### Level 2: `_score_source()` unit tests

```bash
python -c "
from processing.deduplicator import _score_source

# Deep article path beats shallow path
article = {'url': 'https://openai.com/research/gpt-5-release', 'anchor_text': 'Read more'}
homepage = {'url': 'https://openai.com/', 'anchor_text': 'Read the full announcement here'}
assert _score_source(article) > _score_source(homepage), 'Deep path should score higher than homepage even with shorter anchor'

# Among equal path depth, longer anchor wins
short_anchor = {'url': 'https://blog.com/post/ai-news', 'anchor_text': 'here'}
long_anchor  = {'url': 'https://blog.com/post/ai-news', 'anchor_text': 'Read the full GPT-5 announcement'}
assert _score_source(long_anchor) > _score_source(short_anchor), 'Longer anchor should score higher at equal path depth'

# Path depth counts non-empty segments only
assert _score_source({'url': 'https://example.com/a/b/c', 'anchor_text': ''}) == (3, 0)
assert _score_source({'url': 'https://example.com/', 'anchor_text': ''}) == (0, 0)
assert _score_source({'url': 'https://example.com/blog', 'anchor_text': 'x'}) == (1, 1)

# Error-safe: malformed URL falls back to depth 0
assert _score_source({'url': 'not-a-url', 'anchor_text': 'hello'}) == (0, 5)

print('Level 2 PASSED: _score_source unit tests OK')
"
```

### Level 3: `_build_sources()` always returns 0 or 1 sources

```bash
python -c "
from processing.deduplicator import _build_sources
from processing.embedder import StoryChunk

# Single chunk with multiple links → best selected
chunk = StoryChunk(
    text='OpenAI released GPT-5 today.',
    sender='AI Weekly',
    links=[
        {'url': 'https://openai.com/', 'anchor_text': 'here'},
        {'url': 'https://openai.com/research/gpt-5', 'anchor_text': 'Read more'},
        {'url': 'https://techcrunch.com/2026/03/17/openai-gpt5', 'anchor_text': 'TechCrunch coverage of the release'},
    ]
)
sources = _build_sources([chunk])
assert len(sources) == 1, f'Expected 1 source, got {len(sources)}: {sources}'
# TechCrunch URL has depth 3 and longest anchor — should win
assert sources[0]['url'] == 'https://techcrunch.com/2026/03/17/openai-gpt5', f'Wrong URL selected: {sources[0][\"url\"]}'
print(f'Level 3a PASSED: best source selected = {sources[0][\"url\"]}')

# Multiple chunks from different newsletters → best from all candidates
chunk_a = StoryChunk(text='story', sender='Newsletter A', links=[
    {'url': 'https://example.com/', 'anchor_text': 'homepage link'}
])
chunk_b = StoryChunk(text='story', sender='Newsletter B', links=[
    {'url': 'https://example.com/deep/article/gpt5', 'anchor_text': 'full article'}
])
sources2 = _build_sources([chunk_a, chunk_b])
assert len(sources2) == 1, f'Expected 1 source, got {len(sources2)}'
assert 'deep/article' in sources2[0]['url'], f'Expected deep URL, got {sources2[0][\"url\"]}'
print(f'Level 3b PASSED: best source selected across newsletters = {sources2[0][\"url\"]}')

# No links → empty list (sourceless)
empty_chunk = StoryChunk(text='story', sender='Newsletter C', links=[])
assert _build_sources([empty_chunk]) == []
print('Level 3c PASSED: sourceless cluster returns []')
"
```

### Level 4: Full pipeline — each story has exactly 1 source

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>/dev/null | python3 -c "
import sys, json
result = json.load(sys.stdin)
stories = result['stories']
assert len(stories) > 0, 'No stories generated'
bad = [(i, len(s['sources'])) for i, s in enumerate(stories) if len(s['sources']) != 1]
assert not bad, f'Stories with source count != 1: {bad}'
print(f'Level 4 PASSED: all {len(stories)} stories have exactly 1 source')
"
```

### Level 5: Pipeline summary (stage counts and story count)

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
```

Expected: `story_count` > 0; `Generated N digest entry/entries` where N > 0; sourceless count ≤ 64 (equal or lower than pre-change baseline).

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_score_source` is importable from `processing.deduplicator`
- [ ] `_score_source` returns higher score for deeper URL path
- [ ] `_score_source` returns higher score for longer anchor text (as tiebreaker)
- [ ] `_build_sources()` returns a single-element list when links exist
- [ ] `_build_sources()` returns `[]` when no links exist (sourceless — unchanged behavior)
- [ ] Every story in the final digest JSON has exactly 1 source entry
- [ ] No story has `"sources": []` in the output (sourceless stories are still dropped before reaching Claude)

---

## ROLLBACK CONSIDERATIONS

Revert by restoring the original `_build_sources()` body (return full `sources` list) and removing `_score_source()` and the `urlparse` import. No data migration needed — this is a pure in-memory transform.

## ACCEPTANCE CRITERIA

- [ ] `_score_source()` added and returns `(path_depth, anchor_length)` tuple
- [ ] `_build_sources()` returns `[best]` (single-element list) or `[]` (empty)
- [ ] All stories in pipeline output have `len(sources) == 1`
- [ ] No sourceless stories appear in pipeline output (unchanged behavior)
- [ ] Sourceless story count does not increase vs. pre-change baseline

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  ```
  python -c "
  from processing.deduplicator import deduplicate, _build_sources, _score_source
  print('Level 1 PASSED: all symbols importable')
  "
  ```
  Expected output or result:
  ```
  Level 1 PASSED: all symbols importable
  ```

- Item to check:
  ```
  python -c "
  from processing.deduplicator import _score_source

  article = {'url': 'https://openai.com/research/gpt-5-release', 'anchor_text': 'Read more'}
  homepage = {'url': 'https://openai.com/', 'anchor_text': 'Read the full announcement here'}
  assert _score_source(article) > _score_source(homepage), 'Deep path should score higher than homepage even with shorter anchor'

  short_anchor = {'url': 'https://blog.com/post/ai-news', 'anchor_text': 'here'}
  long_anchor  = {'url': 'https://blog.com/post/ai-news', 'anchor_text': 'Read the full GPT-5 announcement'}
  assert _score_source(long_anchor) > _score_source(short_anchor), 'Longer anchor should score higher at equal path depth'

  assert _score_source({'url': 'https://example.com/a/b/c', 'anchor_text': ''}) == (3, 0)
  assert _score_source({'url': 'https://example.com/', 'anchor_text': ''}) == (0, 0)
  assert _score_source({'url': 'https://example.com/blog', 'anchor_text': 'x'}) == (1, 1)
  assert _score_source({'url': 'not-a-url', 'anchor_text': 'hello'}) == (0, 5)

  print('Level 2 PASSED: _score_source unit tests OK')
  "
  ```
  Expected output or result:
  ```
  Level 2 PASSED: _score_source unit tests OK
  ```

- Item to check:
  ```
  python -c "
  from processing.deduplicator import _build_sources
  from processing.embedder import StoryChunk

  chunk = StoryChunk(
      text='OpenAI released GPT-5 today.',
      sender='AI Weekly',
      links=[
          {'url': 'https://openai.com/', 'anchor_text': 'here'},
          {'url': 'https://openai.com/research/gpt-5', 'anchor_text': 'Read more'},
          {'url': 'https://techcrunch.com/2026/03/17/openai-gpt5', 'anchor_text': 'TechCrunch coverage of the release'},
      ]
  )
  sources = _build_sources([chunk])
  assert len(sources) == 1, f'Expected 1 source, got {len(sources)}: {sources}'
  assert sources[0]['url'] == 'https://techcrunch.com/2026/03/17/openai-gpt5', f'Wrong URL selected: {sources[0][\"url\"]}'
  print(f'Level 3a PASSED: best source selected = {sources[0][\"url\"]}')

  chunk_a = StoryChunk(text='story', sender='Newsletter A', links=[
      {'url': 'https://example.com/', 'anchor_text': 'homepage link'}
  ])
  chunk_b = StoryChunk(text='story', sender='Newsletter B', links=[
      {'url': 'https://example.com/deep/article/gpt5', 'anchor_text': 'full article'}
  ])
  sources2 = _build_sources([chunk_a, chunk_b])
  assert len(sources2) == 1, f'Expected 1 source, got {len(sources2)}'
  assert 'deep/article' in sources2[0]['url'], f'Expected deep URL, got {sources2[0][\"url\"]}'
  print(f'Level 3b PASSED: best source selected across newsletters = {sources2[0][\"url\"]}')

  empty_chunk = StoryChunk(text='story', sender='Newsletter C', links=[])
  assert _build_sources([empty_chunk]) == []
  print('Level 3c PASSED: sourceless cluster returns []')
  "
  ```
  Expected output or result:
  ```
  Level 3a PASSED: best source selected = https://techcrunch.com/2026/03/17/openai-gpt5
  Level 3b PASSED: best source selected across newsletters = https://example.com/deep/article/gpt5
  Level 3c PASSED: sourceless cluster returns []
  ```

- Item to check:
  ```
  python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>/dev/null | python3 -c "
  import sys, json
  result = json.load(sys.stdin)
  stories = result['stories']
  assert len(stories) > 0, 'No stories generated'
  bad = [(i, len(s['sources'])) for i, s in enumerate(stories) if len(s['sources']) != 1]
  assert not bad, f'Stories with source count != 1: {bad}'
  print(f'Level 4 PASSED: all {len(stories)} stories have exactly 1 source')
  "
  ```
  Expected output or result:
  ```
  Level 4 PASSED: all N stories have exactly 1 source
  ```
  where N is the number of generated stories (> 0).

- Item to check:
  ```
  python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
  ```
  Expected output or result:
  All 5 stages complete. `story_count: N` where N > 0. `Generated N digest entry/entries` where N > 0. `Dropped N sourceless story group(s)` count ≤ 64.

---

## NOTES

- **Why `path_depth` first, `anchor_length` second?** Path depth is a stronger signal. A homepage URL (`/`) with a long anchor is less useful than a specific article URL (`/blog/2026/story-title`) with a short anchor. Anchor length breaks ties at equal path depth.
- **Why not use the newsletter name for scoring?** Newsletter name has no quality signal — a story from "The Batch" is no better sourced than one from "TLDR AI". URL structure and anchor text are domain-neutral heuristics.
- **Why return `list[dict]` with 1 element rather than `dict`?** Preserves the existing API shape `"sources": [...]` downstream in `claude_client.py`, `digest_builder.py`, and the frontend. No other file needs to change.
- **Multi-newsletter attribution is reduced to single-newsletter.** A story covered by 3 newsletters now shows only the newsletter that contributed the best-scoring link. This is an explicit trade-off per the requirement ("exactly one source"). The `newsletter` field on that source still correctly identifies which newsletter the link came from.
- **Confidence score: 9.5/10** — isolated change to one function in one file, with deterministic, testable scoring logic.
