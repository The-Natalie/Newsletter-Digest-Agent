# Feature: hybrid-dedup-llm-confirmation

The following plan should be complete, but validate documentation and codebase patterns before implementing.

Pay close attention to imports — several files currently import non-existent symbols (`StoryGroup`, `StoryChunk`, `StoryRecord` from wrong modules). Read every file you're modifying before editing.

---

## Feature Description

Two-stage deduplication:

- **Stage 1 (embedding)**: Lower the clustering threshold from 0.78 → 0.65 to catch more cross-newsletter same-story pairs. Already implemented in `embedder.py`; this plan lowers the default and adds candidate detection.
- **Stage 2 (LLM)**: For pairs of Stage 1 clusters whose best items score 0.45–0.65 cosine similarity (too ambiguous for embeddings alone), ask Claude to confirm whether they cover the same story. Confirmed pairs are merged before representative selection.

This plan also rewrites `claude_client.py` and `digest_builder.py` (required dependency — both are currently broken; they import `StoryGroup` which no longer exists) and deletes the obsolete `ai/story_reviewer.py`.

---

## User Story

As a user running a newsletter digest,
I want stories from different newsletters covering the same event to be deduplicated even when writing style and length differ,
So that I see each story once, represented by the most complete version available.

---

## Problem Statement

At threshold=0.78, only 5 of 104 articles were deduplicated across 5 newsletters on a single day. Cross-newsletter same-story pairs typically score 0.55–0.75 (same event, different prose). Lowering to 0.65 catches more, but may over-merge topically related stories. LLM confirmation on the 0.45–0.65 band resolves ambiguous cases accurately.

---

## Scope

**In scope:**
- Lower `dedup_threshold` default to 0.65
- Add `dedup_candidate_min` config setting (default 0.45)
- Add `find_candidate_cluster_pairs()` to `embedder.py`
- Add `merge_confirmed_clusters()` to `deduplicator.py`
- Rewrite `claude_client.py`: `filter_stories()` + `confirm_dedup_candidates()`
- Rewrite `digest_builder.py`: 6-stage pipeline
- Delete `ai/story_reviewer.py` and `tests/test_story_reviewer.py`
- New tests for all new functions

**Out of scope:**
- Frontend changes
- Database schema changes
- PDF export changes
- API route changes (response shape change is backwards-compatible)

---

## Solution Statement

Add `find_candidate_cluster_pairs()` to `embedder.py`: encode stories, compute full similarity matrix, find cross-cluster pairs scoring in [0.45, 0.65). Add `merge_confirmed_clusters()` to `deduplicator.py`: union-find merge of clusters based on LLM decisions. Add `confirm_dedup_candidates()` to `claude_client.py`: async tool-use call that returns `same_story: bool` per candidate pair. Wire these in `digest_builder.py` between embedding and representative selection.

---

## Feature Metadata

**Feature Type**: Enhancement + required rewrites
**Estimated Complexity**: Medium-High
**Primary Systems Affected**: `embedder.py`, `deduplicator.py`, `claude_client.py`, `digest_builder.py`
**Dependencies**: `sentence_transformers.util.cos_sim`, `anthropic` SDK (already present)
**Assumptions**:
- `sentence_transformers` `cos_sim()` is available in `st_util` (already imported in `embedder.py`)
- `AsyncAnthropic` pattern from `story_reviewer.py` is the correct pattern for new LLM functions
- `select_representative` in `deduplicator.py` is used to pick one story per cluster for LLM review

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `processing/embedder.py` (entire file, 72 lines) — current embedding + clustering; note that `st_util` is already imported (has `cos_sim`); `community_detection` is from same module
- `processing/deduplicator.py` (entire file, 91 lines) — `select_representative` and `deduplicate`; `deduplicate` takes `list[list[StoryRecord]]`; note the large-cluster warning at line 76
- `ai/story_reviewer.py` (entire file) — the KEEP/DROP LLM pattern to port into new `filter_stories()`; this file is deleted after porting
- `ai/claude_client.py` (entire file) — currently broken (imports `StoryGroup` at line 9); full rewrite required; do NOT preserve any existing code
- `processing/digest_builder.py` (entire file) — currently broken (imports `story_reviewer` at line 13); full rewrite of pipeline; stage logging pattern to preserve
- `config.py` (entire file, 29 lines) — `Settings` class; add `dedup_candidate_min`; lower `dedup_threshold` default
- `ingestion/email_parser.py` (lines 1–15) — `StoryRecord` dataclass definition; verify field names before using
- `tests/test_deduplicator.py` — test pattern: `_record()` helper at line 11; all tests use `StoryRecord` directly
- `tests/test_claude_client.py` (entire file) — currently broken (imports `StoryGroup`, `StoryChunk`); full replacement required
- `.env.example` — update `DEDUP_THRESHOLD` docs + add `DEDUP_CANDIDATE_MIN`

### Files to DELETE

- `ai/story_reviewer.py`
- `tests/test_story_reviewer.py`

### New Files to Create

- `tests/test_embedder.py` — unit tests for `find_candidate_cluster_pairs`

---

## Patterns to Follow

**Async LLM calls** — mirror `story_reviewer.py` pattern:
```python
_client: AsyncAnthropic | None = None

def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client
```

**Tool-use schema** — mirror `story_reviewer.py` `_TOOL_SCHEMA` structure:
```python
_TOOL_SCHEMA = {
    "name": "...",
    "description": "...",
    "input_schema": {
        "type": "object",
        "properties": {"decisions": {"type": "array", "items": {...}}},
        "required": ["decisions"],
    },
}
```

**Fail-open on LLM errors** — mirror `story_reviewer.py` lines 180–202 and `digest_builder.py` lines 93–101:
- Tool use block missing → keep all (fail-open)
- Decision count mismatch → keep all (fail-open)
- `anthropic.APIError` → log + propagate; caller catches

**Stage logging** — mirror `digest_builder.py` lines 71–120:
```python
logger.info("Stage X/6 — Description", ...)
```

**Batch splitting** — mirror `story_reviewer.py` lines 134–135:
```python
batches = [items[i:i + _BATCH_SIZE] for i in range(0, len(items), _BATCH_SIZE)]
```

**Union-find (new pattern)** — for `merge_confirmed_clusters`:
```python
parent = list(range(n))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]  # path compression
        x = parent[x]
    return x
def union(x, y):
    px, py = find(x), find(y)
    if px != py:
        parent[px] = py
```

**`from __future__ import annotations`** — all files use this; include at top of every file written

**`sys.path` in tests** — mirror `tests/test_deduplicator.py` lines 1–5:
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**`StoryRecord` field names** (verify from `email_parser.py` before using):
- `title: str | None`
- `body: str`
- `links: list[str]`
- `newsletter: str`
- `date: str`
- `source_count: int`

---

## IMPLEMENTATION PLAN

### Phase 1: Config + Foundational Layer

Update settings with two dedup thresholds. No logic changes yet.

### Phase 2: Embedding — Candidate Pair Detection

Add `find_candidate_cluster_pairs()` to `embedder.py`. Computes full cosine similarity matrix and returns cluster-index pairs in the candidate band.

### Phase 3: Deduplicator — Cluster Merging

Add `merge_confirmed_clusters()` to `deduplicator.py`. Union-find merge of clusters. `select_representative` and `deduplicate` unchanged.

### Phase 4: LLM Layer — Rewrite `claude_client.py`

Replace broken file with two functions:
1. `filter_stories()` — binary KEEP/DROP with confidence (ported from `story_reviewer.py`)
2. `confirm_dedup_candidates()` — new LLM dedup confirmation

### Phase 5: Pipeline — Rewrite `digest_builder.py`

Six-stage pipeline. Remove `story_reviewer` import. Wire candidate detection + LLM confirmation between Stage 3 and Stage 5. Write borderline flags file.

### Phase 6: Cleanup — Delete Obsolete Files

Delete `ai/story_reviewer.py` and `tests/test_story_reviewer.py`.

### Phase 7: Tests

New `tests/test_embedder.py`. Add to `tests/test_deduplicator.py`. Replace `tests/test_claude_client.py`.

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order, top to bottom.

---

### Task 1 — UPDATE `config.py`

- **IMPLEMENT**: Lower `dedup_threshold` default from `0.78` → `0.65`. Add `dedup_candidate_min: float = 0.45` below it.
- **PATTERN**: `config.py` line 19 — existing `dedup_threshold` field
- **GOTCHA**: `pydantic-settings` reads from `.env`; the default only applies when the env var is absent. Test with `python -c "from config import settings; print(settings.dedup_threshold, settings.dedup_candidate_min)"`.
- **VALIDATE**: `python -c "from config import settings; assert settings.dedup_threshold == 0.65; assert settings.dedup_candidate_min == 0.45; print('OK')"`

---

### Task 2 — UPDATE `processing/embedder.py`

- **IMPLEMENT**: Add function `find_candidate_cluster_pairs` below `embed_and_cluster`. Signature:
  ```python
  def find_candidate_cluster_pairs(
      story_records: list[StoryRecord],
      clusters: list[list[StoryRecord]],
      candidate_min: float,
      stage1_threshold: float,
  ) -> list[tuple[int, int]]:
  ```

  Implementation steps:
  1. Return `[]` immediately if `len(story_records) < 2` or `len(clusters) < 2`
  2. Build `item_to_cluster: dict[int, int]` using `id(record)` as key — maps each record's object ID to its cluster index
  3. Encode all `story_records` using `_get_model().encode(...)` with `convert_to_tensor=True, show_progress_bar=False` and `[_encoding_text(r) for r in story_records]`
  4. Compute `sim_matrix = st_util.cos_sim(embeddings, embeddings)` — NxN float32 tensor
  5. Iterate upper triangle (`i < j`): if `candidate_min <= sim_matrix[i][j].item() < stage1_threshold`, map `story_records[i]` and `story_records[j]` to their cluster indices; if different clusters, add `(min(ci, cj), max(ci, cj))` to a set
  6. Return sorted list of unique cluster pairs from the set
  7. Log: `"Found %d candidate cluster pair(s) in similarity band [%.2f, %.2f)"`

- **IMPORTS**: No new imports needed — `st_util` already imported at line 6; `StoryRecord` already imported at line 9
- **GOTCHA**: Use `id(record)` for the item→cluster mapping because `StoryRecord` is a dataclass and identity (not equality) is needed. Build the map by iterating `enumerate(clusters)` and then iterating records within each cluster.
- **GOTCHA**: `sim_matrix[i][j].item()` extracts scalar float from tensor. Do not compare tensor to float directly.
- **GOTCHA**: For N=100 stories, iterating O(N²) pairs in Python is ~5000 iterations — acceptable. Do not add complexity for vectorized approach.
- **VALIDATE**: `python -c "import ingestion.email_parser; from processing.embedder import find_candidate_cluster_pairs; print('OK')"`

---

### Task 3 — UPDATE `processing/deduplicator.py`

- **IMPLEMENT**: Add function `merge_confirmed_clusters` below `select_representative` (before `deduplicate`). Signature:
  ```python
  def merge_confirmed_clusters(
      clusters: list[list[StoryRecord]],
      confirmed_pairs: list[tuple[int, int]],
  ) -> list[list[StoryRecord]]:
  ```

  Implementation steps:
  1. Return `clusters[:]` immediately if `confirmed_pairs` is empty
  2. Union-find: `parent = list(range(len(clusters)))` with path-compressed `find(x)` and `union(x, y)`
  3. Call `union(ci, cj)` for each `(ci, cj)` in `confirmed_pairs`
  4. Group cluster indices by root: `groups: dict[int, list[int]] = defaultdict(list)` — `groups[find(i)].append(i)`
  5. Build merged result: for each root in `groups`, flatten all records from those clusters into one list; order: by cluster index within each merged group
  6. Log: `"Merged %d cluster pair(s) → %d final cluster(s) (was %d)"`
  7. Return merged cluster list

- **IMPORTS**: Add `from collections import defaultdict` at top (after existing imports)
- **GOTCHA**: The returned clusters are a new list of new sublists, but the `StoryRecord` objects inside are the originals (not copies) — this is correct; `select_representative` creates copies via `dataclasses.replace`
- **VALIDATE**: `python -c "from processing.deduplicator import merge_confirmed_clusters; print('OK')"`

---

### Task 4 — DELETE `ai/story_reviewer.py`

- **REMOVE**: Delete the file `ai/story_reviewer.py`
- **GOTCHA**: `digest_builder.py` currently imports from this file — it will be rewritten in Task 6 to remove that import. Do Task 4 and Task 6 in sequence; do NOT run the test suite between Tasks 4–6 as it will fail due to missing imports.
- **VALIDATE**: `python -c "import os; assert not os.path.exists('ai/story_reviewer.py'); print('OK')"`

---

### Task 5 — DELETE `tests/test_story_reviewer.py`

- **REMOVE**: Delete the file `tests/test_story_reviewer.py`
- **VALIDATE**: `python -c "import os; assert not os.path.exists('tests/test_story_reviewer.py'); print('OK')"`

---

### Task 6 — REWRITE `ai/claude_client.py`

Delete all existing content and write a new file with two functions. The existing file is broken (imports `StoryGroup` from `processing.deduplicator` which does not exist).

**New file structure**:

```python
from __future__ import annotations

import json
import logging
import os

import anthropic
from anthropic import AsyncAnthropic

from config import settings
from ingestion.email_parser import StoryRecord

logger = logging.getLogger(__name__)

# ── Shared client ──────────────────────────────────────────────────────────────

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    """Lazy-initialize and cache the AsyncAnthropic client."""
    global _client
    if _client is None:
        logger.info("Initializing AsyncAnthropic client (model=%s)", settings.claude_model)
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


# ── filter_stories ─────────────────────────────────────────────────────────────

_FILTER_TOOL_NAME = "filter_stories"
_FILTER_BATCH_SIZE = 25
_FILTER_MAX_BODY_CHARS = 300

_FILTER_TOOL_SCHEMA: dict = {
    "name": _FILTER_TOOL_NAME,
    "description": (
        "Classify each story as KEEP or DROP. "
        "Return one decision per story, in the same order as the input."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per story, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "keep": {
                            "type": "boolean",
                            "description": "True = KEEP, False = DROP.",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "borderline"],
                            "description": "Use 'borderline' when uncertain.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One sentence explaining the decision. Required when confidence is 'borderline'.",
                        },
                    },
                    "required": ["keep", "confidence", "reasoning"],
                },
            }
        },
        "required": ["decisions"],
    },
}


def _filter_system_prompt(folder: str) -> str:
    return (
        f"You are a content filter for a newsletter digest focused on {folder}.\n\n"
        "Classify each story as KEEP or DROP.\n\n"
        "KEEP if the item contains:\n"
        "- A real news story, article, or announcement\n"
        "- A product launch, tool release, research paper, or report\n"
        "- A job listing or career opportunity\n"
        "- Sponsor content that includes a concrete offer, discount, free tool, "
        "webinar, or substantive explanation with real value to the reader\n\n"
        "DROP if the item contains only:\n"
        "- Newsletter housekeeping (subscription management, unsubscribe prompts)\n"
        "- Audience growth content: 'advertise with us', referral programs, "
        "generic brand-awareness blurbs with no real content\n"
        "- Legal / footer boilerplate (terms, privacy policy, all rights reserved)\n"
        "- Reader feedback requests (surveys, polls, 'share your thoughts')\n"
        "- Editorial shell content with no actual information (intros, outros, "
        "'that's all for this week')\n"
        "- Pure call-to-action blocks with no substantive content beyond the CTA itself\n\n"
        "When in doubt, KEEP. Only DROP on clear non-story signals. "
        "Never drop short valid stories — a one-sentence item with a link is valid."
    )


def _build_filter_message(stories: list[StoryRecord], folder: str) -> str:
    lines: list[str] = [
        f"Below are {len(stories)} story item(s) from newsletters about {folder}.\n"
    ]
    for i, story in enumerate(stories, 1):
        lines.append(f"## Story {i}")
        if story.title:
            lines.append(f"Title: {story.title}")
        lines.append(f"Newsletter: {story.newsletter}")
        lines.append(f"Body: {story.body[:_FILTER_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_FILTER_TOOL_NAME}` tool to return {len(stories)} decisions "
        f"(keep, confidence, reasoning) in the same order."
    )
    return "\n".join(lines)


async def filter_stories(
    stories: list[StoryRecord],
    folder: str,
) -> tuple[list[StoryRecord], list[dict]]:
    """Binary KEEP/DROP filter for deduplicated story items.

    Args:
        stories: List of StoryRecord objects after deduplication.
        folder: IMAP folder name used as topic context.

    Returns:
        Tuple of (kept, borderline_flags) where:
        - kept: StoryRecord objects the LLM decided to KEEP
        - borderline_flags: List of dicts for flags_latest.jsonl,
          one per item with confidence='borderline'

    On API failure, returns (stories, []) — fail-open: keep all, no flags.
    """
    if not stories:
        return [], []

    client = _get_client()
    batches = [stories[i:i + _FILTER_BATCH_SIZE] for i in range(0, len(stories), _FILTER_BATCH_SIZE)]

    logger.info(
        "LLM filter: %d story/stories in %d batch(es) for folder '%s'",
        len(stories),
        len(batches),
        folder,
    )

    kept: list[StoryRecord] = []
    borderline_flags: list[dict] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_filter_message(batch, folder)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=1024,
                system=_filter_system_prompt(folder),
                messages=[{"role": "user", "content": user_message}],
                tools=[_FILTER_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _FILTER_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error("LLM filter API error on batch %d/%d: %s — keeping all", batch_num, len(batches), exc)
            kept.extend(batch)
            continue

        logger.debug(
            "LLM filter batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning("LLM filter batch %d/%d: no tool_use block — keeping all %d", batch_num, len(batches), len(batch))
            kept.extend(batch)
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM filter batch %d/%d: count mismatch (%d decisions for %d stories) — keeping all",
                batch_num, len(batches), len(decisions), len(batch),
            )
            kept.extend(batch)
            continue

        batch_kept = 0
        batch_dropped = 0
        for story, decision in zip(batch, decisions):
            keep = decision.get("keep", True)
            confidence = decision.get("confidence", "high")
            reasoning = decision.get("reasoning", "")
            if keep:
                kept.append(story)
                batch_kept += 1
            else:
                batch_dropped += 1
            if confidence == "borderline":
                borderline_flags.append({
                    "decision": "KEEP" if keep else "DROP",
                    "confidence": "borderline",
                    "llm_reasoning": reasoning,
                    "item": {
                        "title": story.title,
                        "body": story.body,
                        "link": story.links[0] if story.links else None,
                        "newsletter": story.newsletter,
                        "date": story.date,
                    },
                })

        logger.info(
            "LLM filter batch %d/%d: kept %d / %d (dropped %d)",
            batch_num, len(batches), batch_kept, len(batch), batch_dropped,
        )

    return kept, borderline_flags


# ── confirm_dedup_candidates ───────────────────────────────────────────────────

_DEDUP_TOOL_NAME = "confirm_dedup"
_DEDUP_BATCH_SIZE = 20
_DEDUP_MAX_BODY_CHARS = 300

_DEDUP_TOOL_SCHEMA: dict = {
    "name": _DEDUP_TOOL_NAME,
    "description": (
        "For each candidate group, decide if the stories describe the same real-world "
        "event or announcement. Return true only when clearly the same story."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per candidate group, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "same_story": {
                            "type": "boolean",
                            "description": (
                                "True if all items in this group are covering the same "
                                "real-world event or announcement. False if they are "
                                "distinct stories, even if topically related."
                            ),
                        },
                    },
                    "required": ["same_story"],
                },
            }
        },
        "required": ["decisions"],
    },
}

_DEDUP_SYSTEM_PROMPT = (
    "You are a deduplication assistant for a newsletter digest. "
    "You will be shown groups of story excerpts from different newsletters. "
    "For each group, decide if the stories are covering the SAME real-world event or announcement.\n\n"
    "Return same_story=true ONLY when the stories clearly describe the same specific event: "
    "the same company action, product launch, research result, or news item. "
    "Return same_story=false for stories that are merely on the same topic or theme. "
    "When uncertain, return false — it is better to show a near-duplicate than to lose a distinct story."
)


def _build_dedup_message(candidate_groups: list[list[StoryRecord]]) -> str:
    lines: list[str] = [
        f"Below are {len(candidate_groups)} candidate group(s). "
        "Each group contains 2 story excerpts from different newsletters that "
        "scored 0.45–0.65 cosine similarity (ambiguous range).\n"
    ]
    for i, group in enumerate(candidate_groups, 1):
        lines.append(f"## Group {i}")
        for j, story in enumerate(group, 1):
            label = chr(ord('A') + j - 1)  # A, B, C...
            lines.append(f"Story {label} (from {story.newsletter}):")
            if story.title:
                lines.append(f"  Title: {story.title}")
            lines.append(f"  Body: {story.body[:_DEDUP_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_DEDUP_TOOL_NAME}` tool to return {len(candidate_groups)} decisions "
        "(same_story) in the same order."
    )
    return "\n".join(lines)


async def confirm_dedup_candidates(
    candidate_groups: list[list[StoryRecord]],
) -> list[bool]:
    """LLM Stage 2 dedup: confirm whether each candidate group covers the same story.

    Args:
        candidate_groups: List of groups (each 2-5 StoryRecord objects, one per
                          Stage 1 cluster) whose embedding similarity fell in the
                          0.45–0.65 candidate band.

    Returns:
        List of bool, one per group. True = same story (merge those clusters).
        On API failure, returns all-False (fail-open: keep clusters separate).
    """
    if not candidate_groups:
        return []

    client = _get_client()
    batches = [candidate_groups[i:i + _DEDUP_BATCH_SIZE] for i in range(0, len(candidate_groups), _DEDUP_BATCH_SIZE)]

    logger.info(
        "LLM dedup confirmation: %d candidate group(s) in %d batch(es)",
        len(candidate_groups),
        len(batches),
    )

    results: list[bool] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_dedup_message(batch)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                system=_DEDUP_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[_DEDUP_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _DEDUP_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error("LLM dedup API error on batch %d/%d: %s — treating all as distinct", batch_num, len(batches), exc)
            results.extend([False] * len(batch))
            continue

        logger.debug(
            "LLM dedup batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning("LLM dedup batch %d/%d: no tool_use block — treating all as distinct", batch_num, len(batches))
            results.extend([False] * len(batch))
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM dedup batch %d/%d: count mismatch (%d decisions for %d groups) — treating all as distinct",
                batch_num, len(batches), len(decisions), len(batch),
            )
            results.extend([False] * len(batch))
            continue

        batch_confirmed = sum(1 for d in decisions if d.get("same_story", False))
        logger.info(
            "LLM dedup batch %d/%d: confirmed %d / %d as same-story",
            batch_num, len(batches), batch_confirmed, len(batch),
        )
        results.extend(bool(d.get("same_story", False)) for d in decisions)

    return results
```

- **IMPORTS**: `json`, `os` needed for flags file writing (though flags file is written by `digest_builder.py`); actually `json` and `os` are NOT needed in `claude_client.py` — only `anthropic`, `logging`, `config.settings`, and `StoryRecord`. Do not add unused imports.
- **GOTCHA**: The existing `claude_client.py` has `from processing.deduplicator import StoryGroup` at line 9 — this import causes an `ImportError` on every import. Delete it entirely.
- **GOTCHA**: The existing `generate_digest` function (summarization) is NOT ported. Per CLAUDE.md and prime-summary.md: "No AI generation. The pipeline extracts and selects — it does not rewrite, summarize."
- **VALIDATE**: `python -c "from ai.claude_client import filter_stories, confirm_dedup_candidates; print('OK')"`

---

### Task 7 — REWRITE `processing/digest_builder.py`

Delete all existing content. Write a new 6-stage pipeline.

**New file structure** (write this completely):

```python
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa

from ai.claude_client import confirm_dedup_candidates, filter_stories
from database import async_session, digest_runs
from ingestion.email_parser import parse_emails
from ingestion.imap_client import fetch_emails
from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative
from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs
from config import settings

logger = logging.getLogger(__name__)

_FLAGS_PATH = "data/flags_latest.jsonl"


async def build_digest(
    folder: str,
    date_start: date,
    date_end: date,
) -> dict:
    """Run the full digest pipeline end-to-end and persist the result.

    Pipeline stages:
        1. Fetch emails from IMAP
        2. Parse emails → StoryRecord list
        3. Embed + cluster (Stage 1 dedup, threshold=settings.dedup_threshold)
        4. LLM confirms candidate pairs (Stage 2 dedup, band [dedup_candidate_min, threshold))
        5. Deduplicate → select one representative per final cluster
        6. LLM filter → binary keep/drop on representatives

    Returns:
        Digest response dict: id, generated_at, folder, date_start, date_end,
        story_count, stories (list of story dicts).
    """
    run_id = str(uuid.uuid4())
    run_at = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_session() as session:
        await session.execute(
            digest_runs.insert().values(
                id=run_id,
                run_at=run_at,
                folder=folder,
                date_start=date_start,
                date_end=date_end,
                status="pending",
            )
        )
        await session.commit()

    logger.info("Digest run started: id=%s folder='%s' %s→%s", run_id[:8], folder, date_start, date_end)

    try:
        # ── Stage 1: Fetch emails ──────────────────────────────────────────
        logger.info("Stage 1/6 — Fetching emails from '%s'", folder)
        raw_emails = fetch_emails(folder, date_start, date_end)
        logger.info("Stage 1/6 — Fetched %d raw email(s)", len(raw_emails))

        # ── Stage 2: Parse emails ─────────────────────────────────────────
        logger.info("Stage 2/6 — Parsing emails into story records")
        story_records = parse_emails(raw_emails)
        logger.info("Stage 2/6 — Parsed %d story record(s)", len(story_records))

        # ── Stage 3: Embed + Stage 1 cluster ─────────────────────────────
        logger.info(
            "Stage 3/6 — Embedding and clustering (Stage 1 threshold=%.2f)",
            settings.dedup_threshold,
        )
        clusters = embed_and_cluster(story_records)
        logger.info("Stage 3/6 — Produced %d cluster(s)", len(clusters))

        # ── Stage 4: LLM Stage 2 dedup ────────────────────────────────────
        logger.info(
            "Stage 4/6 — Finding candidate pairs (band [%.2f, %.2f)) and confirming via LLM",
            settings.dedup_candidate_min,
            settings.dedup_threshold,
        )
        candidate_pairs = find_candidate_cluster_pairs(
            story_records,
            clusters,
            candidate_min=settings.dedup_candidate_min,
            stage1_threshold=settings.dedup_threshold,
        )
        logger.info("Stage 4/6 — Found %d candidate cluster pair(s)", len(candidate_pairs))

        if candidate_pairs:
            candidate_groups = [
                [select_representative(clusters[ci]), select_representative(clusters[cj])]
                for ci, cj in candidate_pairs
            ]
            same_story_mask = await confirm_dedup_candidates(candidate_groups)
            confirmed = [
                (ci, cj)
                for (ci, cj), same in zip(candidate_pairs, same_story_mask)
                if same
            ]
            logger.info("Stage 4/6 — LLM confirmed %d pair(s) as same-story", len(confirmed))
            if confirmed:
                clusters = merge_confirmed_clusters(clusters, confirmed)
                logger.info("Stage 4/6 — Clusters after merge: %d", len(clusters))

        # ── Stage 5: Deduplicate ──────────────────────────────────────────
        logger.info("Stage 5/6 — Selecting representatives from %d cluster(s)", len(clusters))
        representatives = deduplicate(clusters)
        logger.info("Stage 5/6 — %d representative(s) selected", len(representatives))

        # ── Stage 6: LLM filter ───────────────────────────────────────────
        logger.info("Stage 6/6 — Running LLM keep/drop filter on %d story/stories", len(representatives))
        kept, borderline_flags = await filter_stories(representatives, folder)
        dropped_count = len(representatives) - len(kept)
        logger.info(
            "Stage 6/6 — Kept %d / %d (dropped %d, borderline %d)",
            len(kept), len(representatives), dropped_count, len(borderline_flags),
        )

        # Write borderline flags file (development artifact, overwritten each run)
        os.makedirs("data", exist_ok=True)
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            for flag in borderline_flags:
                f.write(json.dumps(flag, ensure_ascii=False) + "\n")

        print(
            f"Pipeline complete: {len(kept)} kept, {dropped_count} dropped, "
            f"{len(borderline_flags)} flagged as borderline. "
            f"Flagged records written to {_FLAGS_PATH}."
        )

        # ── Build response dict ───────────────────────────────────────────
        stories = [
            {
                "title": r.title,
                "body": r.body,
                "link": r.links[0] if r.links else None,
                "links": r.links,
                "newsletter": r.newsletter,
                "date": r.date,
                "source_count": r.source_count,
            }
            for r in kept
        ]

        response: dict = {
            "id": run_id,
            "generated_at": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "folder": folder,
            "date_start": date_start.isoformat(),
            "date_end": date_end.isoformat(),
            "story_count": len(stories),
            "stories": stories,
        }

        async with async_session() as session:
            await session.execute(
                digest_runs.update()
                .where(digest_runs.c.id == run_id)
                .values(
                    status="complete",
                    story_count=len(stories),
                    output_json=json.dumps(response),
                )
            )
            await session.commit()

        logger.info("Digest run complete: id=%s stories=%d", run_id[:8], len(stories))
        return response

    except Exception as exc:
        logger.error("Digest run failed: id=%s error=%s", run_id[:8], exc)
        async with async_session() as session:
            await session.execute(
                digest_runs.update()
                .where(digest_runs.c.id == run_id)
                .values(status="failed", error_message=str(exc))
            )
            await session.commit()
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Generate a newsletter digest from an IMAP folder.")
    parser.add_argument("--folder", required=True, help="IMAP folder name")
    parser.add_argument("--start", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--end", required=True, metavar="YYYY-MM-DD")
    args = parser.parse_args()
    result = asyncio.run(build_digest(args.folder, date.fromisoformat(args.start), date.fromisoformat(args.end)))
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

- **GOTCHA**: Do not import `story_reviewer` — it is deleted. Do not import `generate_digest` — it is gone.
- **GOTCHA**: `select_representative` is imported from `processing.deduplicator` for use in building candidate groups. This is distinct from `deduplicate`.
- **GOTCHA**: The `data/` directory may not exist on first run — `os.makedirs("data", exist_ok=True)` handles this.
- **VALIDATE**: `python -c "import processing.digest_builder; print('OK')"`

---

### Task 8 — UPDATE `.env.example`

- **IMPLEMENT**: In the `# Pipeline Tuning` section, update the `DEDUP_THRESHOLD` entry and add `DEDUP_CANDIDATE_MIN` immediately below it:

```
# DEDUP_THRESHOLD: cosine similarity threshold for Stage 1 embedding-based clustering.
# Range: 0.0–1.0. Higher = stricter matching (fewer merges).
# Default 0.65 works well for cross-newsletter dedup; tune after first real run.
# Stories below DEDUP_CANDIDATE_MIN are never considered duplicates (too dissimilar).
# Stories between DEDUP_CANDIDATE_MIN and DEDUP_THRESHOLD are reviewed by the LLM.
# Stories above DEDUP_THRESHOLD are merged directly (embedding confidence is high).

DEDUP_THRESHOLD=0.65
DEDUP_CANDIDATE_MIN=0.45
```

- **VALIDATE**: `grep -n "DEDUP_CANDIDATE_MIN" .env.example` — should show the new line

---

### Task 9 — CREATE `tests/test_embedder.py`

New test file for `find_candidate_cluster_pairs`. Use simple synthetic embeddings (short text strings, not mock tensors) so the real model runs and produces real similarity scores. For predictability, design test cases where the expected similarity outcome is unambiguous.

**Test cases to implement**:

```python
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import StoryRecord
from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs


def _record(body: str, title: str | None = None, newsletter: str = "Test") -> StoryRecord:
    return StoryRecord(title=title, body=body, links=[], newsletter=newsletter, date="2026-03-17")


# NOTE: these tests call the real sentence-transformers model.
# They are integration-level; each test may take ~0.5s on first run (model load).


def test_find_candidate_cluster_pairs_empty_input():
    """Empty story list → empty result."""
    result = find_candidate_cluster_pairs([], [], 0.45, 0.65)
    assert result == []


def test_find_candidate_cluster_pairs_single_cluster():
    """Single cluster → no cross-cluster pairs possible."""
    r = _record("OpenAI announced a new model today.")
    clusters = [[r]]
    result = find_candidate_cluster_pairs([r], clusters, 0.45, 0.65)
    assert result == []


def test_find_candidate_cluster_pairs_no_pairs_in_band():
    """Clusters with very dissimilar content → no pairs in 0.45–0.65 band."""
    r1 = _record("The recipe calls for two cups of flour, one egg, and some sugar.")
    r2 = _record("NASA launched a new satellite into low Earth orbit yesterday.")
    clusters = embed_and_cluster([r1, r2])
    result = find_candidate_cluster_pairs([r1, r2], clusters, 0.45, 0.65)
    # Very different topics — should score well below 0.45
    assert isinstance(result, list)
    # Verify all returned pairs are cross-cluster (same-cluster pairs excluded)
    for ci, cj in result:
        assert ci != cj


def test_find_candidate_cluster_pairs_returns_unique_pairs():
    """No duplicate cluster pairs in result."""
    r1 = _record("OpenAI released GPT-5 with major reasoning improvements this week.")
    r2 = _record("OpenAI unveiled GPT-5 featuring significantly enhanced reasoning capabilities.")
    r3 = _record("The new GPT-5 model from OpenAI brings stronger reasoning to users.")
    story_records = [r1, r2, r3]
    clusters = embed_and_cluster(story_records)
    result = find_candidate_cluster_pairs(story_records, clusters, 0.30, 0.99)
    # Check uniqueness
    seen = set()
    for pair in result:
        assert pair not in seen, f"Duplicate pair: {pair}"
        seen.add(pair)


def test_find_candidate_cluster_pairs_above_threshold_excluded():
    """Pairs above stage1_threshold are NOT returned (they belong to Stage 1 clusters)."""
    r1 = _record("OpenAI released GPT-5 with major reasoning improvements this week.")
    r2 = _record("OpenAI unveiled GPT-5 featuring significantly enhanced reasoning capabilities.")
    story_records = [r1, r2]
    # These two should cluster together above 0.65 (very similar text).
    # With threshold=0.99 (high), they'd be separate clusters but scored above 0.65 band.
    clusters_high = embed_and_cluster(story_records)  # uses settings.dedup_threshold
    result = find_candidate_cluster_pairs(story_records, clusters_high, 0.45, 0.65)
    # If they're in the same cluster, result is empty (no cross-cluster pair).
    # If they're in different clusters, their sim > 0.65 so excluded from band.
    # Either way, result should not contain pairs scoring >= 0.65.
    assert isinstance(result, list)


def test_find_candidate_cluster_pairs_cluster_indices_in_range():
    """All returned cluster indices are valid indices into the clusters list."""
    r1 = _record("Apple announced new iPhone models at their annual event.")
    r2 = _record("Samsung unveiled new Galaxy phones at a press conference.")
    r3 = _record("Google released the Pixel 9 with improved camera features.")
    story_records = [r1, r2, r3]
    clusters = embed_and_cluster(story_records)
    result = find_candidate_cluster_pairs(story_records, clusters, 0.20, 0.99)
    for ci, cj in result:
        assert 0 <= ci < len(clusters)
        assert 0 <= cj < len(clusters)
        assert ci != cj
```

- **GOTCHA**: These tests use the real sentence-transformers model (it's cached after first call). They are slow on first run (~2-5s for model load, then fast). Do NOT mock the model in these tests — the point is to verify real embedding behavior.
- **GOTCHA**: Do not assert specific similarity scores in tests — the model's outputs can vary slightly across versions. Test structural properties (uniqueness, index validity, empty-result conditions) instead.
- **VALIDATE**: `python -m pytest tests/test_embedder.py -v`

---

### Task 10 — UPDATE `tests/test_deduplicator.py`

Add new tests for `merge_confirmed_clusters` at the end of the existing file. Do NOT modify existing tests.

**Tests to add**:

```python
# ---------------------------------------------------------------------------
# merge_confirmed_clusters tests
# ---------------------------------------------------------------------------

from processing.deduplicator import merge_confirmed_clusters


def test_merge_confirmed_no_pairs_returns_original():
    """Empty confirmed_pairs → clusters returned unchanged."""
    r1 = _record("Story A.")
    r2 = _record("Story B.")
    clusters = [[r1], [r2]]
    result = merge_confirmed_clusters(clusters, [])
    assert len(result) == 2


def test_merge_confirmed_single_pair():
    """One confirmed pair → those two clusters merged into one."""
    r1 = _record("OpenAI announced GPT-5 with reasoning improvements.")
    r2 = _record("OpenAI released GPT-5 featuring enhanced reasoning.")
    clusters = [[r1], [r2]]
    result = merge_confirmed_clusters(clusters, [(0, 1)])
    assert len(result) == 1
    assert len(result[0]) == 2
    bodies = {r.body for r in result[0]}
    assert r1.body in bodies
    assert r2.body in bodies


def test_merge_confirmed_transitivity():
    """Pairs (0,1) and (1,2) → all three clusters merged into one."""
    r1 = _record("Story alpha.")
    r2 = _record("Story beta.")
    r3 = _record("Story gamma.")
    clusters = [[r1], [r2], [r3]]
    result = merge_confirmed_clusters(clusters, [(0, 1), (1, 2)])
    assert len(result) == 1
    assert len(result[0]) == 3


def test_merge_confirmed_unconfirmed_clusters_preserved():
    """Clusters not in any confirmed pair remain as separate clusters."""
    r1 = _record("Story A.")
    r2 = _record("Story B.")
    r3 = _record("Story C — unrelated, should stay separate.")
    clusters = [[r1], [r2], [r3]]
    result = merge_confirmed_clusters(clusters, [(0, 1)])
    assert len(result) == 2
    merged_bodies = {r.body for cluster in result for r in cluster}
    assert r3.body in merged_bodies


def test_merge_confirmed_multi_item_clusters():
    """Clusters with multiple items each: merged cluster contains all items from both."""
    r1a = _record("Story A version 1.")
    r1b = _record("Story A version 2 — longer body with more detail about the announcement.")
    r2a = _record("Story B version 1.")
    r2b = _record("Story B version 2 — longer body with more detail about the second story.")
    clusters = [[r1a, r1b], [r2a, r2b]]
    result = merge_confirmed_clusters(clusters, [(0, 1)])
    assert len(result) == 1
    assert len(result[0]) == 4
```

- **GOTCHA**: The import `from processing.deduplicator import merge_confirmed_clusters` should be added at the top of the file, alongside the existing imports (`select_representative`, `deduplicate`). Update the existing import line.
- **VALIDATE**: `python -m pytest tests/test_deduplicator.py -v`

---

### Task 11 — REPLACE `tests/test_claude_client.py`

Delete all existing content (which imports non-existent `StoryGroup` and `StoryChunk`). Write new tests for the two functions in the new `claude_client.py`.

**New file** — test structural properties only (no live API calls):

```python
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import StoryRecord
from ai.claude_client import (
    _FILTER_BATCH_SIZE,
    _FILTER_TOOL_NAME,
    _FILTER_TOOL_SCHEMA,
    _DEDUP_BATCH_SIZE,
    _DEDUP_TOOL_NAME,
    _DEDUP_TOOL_SCHEMA,
    _build_filter_message,
    _build_dedup_message,
)


def _record(body: str, title: str | None = None, newsletter: str = "Test Newsletter") -> StoryRecord:
    return StoryRecord(title=title, body=body, links=[], newsletter=newsletter, date="2026-03-17")


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
    from ai.claude_client import _FILTER_MAX_BODY_CHARS
    long_body = "X" * (_FILTER_MAX_BODY_CHARS + 100)
    story = _record(long_body)
    msg = _build_filter_message([story], "AI")
    # The long body should be truncated — not the full body present
    assert "X" * (_FILTER_MAX_BODY_CHARS + 100) not in msg


# ── confirm_dedup_candidates constants ───────────────────────────────────────

def test_dedup_batch_size():
    """_DEDUP_BATCH_SIZE is 20."""
    assert _DEDUP_BATCH_SIZE == 20


def test_dedup_tool_name():
    """_DEDUP_TOOL_NAME matches schema name."""
    assert _DEDUP_TOOL_SCHEMA["name"] == _DEDUP_TOOL_NAME


def test_dedup_schema_same_story_field():
    """Dedup tool schema has decisions array with same_story boolean field."""
    items = _DEDUP_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    assert "same_story" in items["properties"]
    assert items["properties"]["same_story"]["type"] == "boolean"


def test_dedup_message_labels_stories_with_newsletter():
    """Dedup message labels each story with its newsletter name."""
    r1 = _record("OpenAI released GPT-5.", newsletter="TLDR")
    r2 = _record("OpenAI unveiled GPT-5 model.", newsletter="The Deep View")
    msg = _build_dedup_message([[r1, r2]])
    assert "TLDR" in msg
    assert "The Deep View" in msg


def test_dedup_message_group_count_matches():
    """Dedup message requests exactly N decisions for N groups."""
    groups = [
        [_record("Story A.", newsletter="NL1"), _record("Story A variant.", newsletter="NL2")],
        [_record("Story B.", newsletter="NL3"), _record("Story B variant.", newsletter="NL4")],
    ]
    msg = _build_dedup_message(groups)
    assert "2 decisions" in msg or "2 candidate group" in msg


def test_dedup_batch_split_50_groups():
    """50 candidate groups split into ceil(50/20) = 3 batches: 20, 20, 10."""
    groups = list(range(50))
    batches = [groups[i:i + _DEDUP_BATCH_SIZE] for i in range(0, len(groups), _DEDUP_BATCH_SIZE)]
    assert len(batches) == 3
    assert len(batches[0]) == 20
    assert len(batches[1]) == 20
    assert len(batches[2]) == 10
```

- **GOTCHA**: All private names imported (`_FILTER_BATCH_SIZE`, `_build_filter_message`, etc.) must match exactly what is defined in the new `claude_client.py`. Verify names before writing tests.
- **VALIDATE**: `python -m pytest tests/test_claude_client.py -v`

---

## TESTING STRATEGY

### Unit Tests (no API, no model)

- `tests/test_deduplicator.py` — `merge_confirmed_clusters` (5 new tests, pure Python)
- `tests/test_claude_client.py` — tool schema structure, batch splitting, message building (no API calls)

### Integration Tests (real sentence-transformers model)

- `tests/test_embedder.py` — `find_candidate_cluster_pairs` with real embeddings (5-6 tests)

### Edge Cases

- Empty inputs to all new functions
- `confirmed_pairs=[]` in `merge_confirmed_clusters` → clusters unchanged
- Transitivity: (A,B) and (B,C) confirmed → A+B+C merged into one cluster
- Single-item cluster passed to `find_candidate_cluster_pairs` → `[]`
- LLM count mismatch in both `filter_stories` and `confirm_dedup_candidates` → fail-open

---

## VALIDATION COMMANDS

### Level 1: Syntax Check

```bash
python -c "from config import settings; assert settings.dedup_threshold == 0.65; assert settings.dedup_candidate_min == 0.45; print('config OK')"
python -c "from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs; print('embedder OK')"
python -c "from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative; print('deduplicator OK')"
python -c "from ai.claude_client import filter_stories, confirm_dedup_candidates; print('claude_client OK')"
python -c "import processing.digest_builder; print('digest_builder OK')"
python -c "import os; assert not os.path.exists('ai/story_reviewer.py'); print('story_reviewer deleted OK')"
```

### Level 2: Full Test Suite

```bash
python -m pytest tests/ -v
```

Expected: all tests pass. Previous count: 81. New expected count: 81 (removed) + new tests added in Tasks 9–11.

### Level 3: Targeted New Tests

```bash
python -m pytest tests/test_deduplicator.py -k "merge_confirmed" -v
python -m pytest tests/test_embedder.py -v
python -m pytest tests/test_claude_client.py -v
```

### Level 4: Manual Spot-Check (no IMAP required)

Run the dedup stages in isolation using test data from the existing test file:

```python
# Save as /tmp/test_hybrid_dedup.py and run: python /tmp/test_hybrid_dedup.py
import sys, os
sys.path.insert(0, "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent")

from ingestion.email_parser import StoryRecord
from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs
from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative
from config import settings

records = [
    StoryRecord(title="OpenAI to Cut Back on Side Projects", body="OpenAI plans to refocus its efforts around coding and business users. Its leaders are actively looking for areas to deprioritize. The company requires a clearer strategic direction.", links=[], newsletter="TLDR", date="2026-03-17"),
    StoryRecord(title="OpenAI to Cut Back on Side Projects", body="OpenAI's 'do everything at once' strategy has put the company on the defensive. Its top executives are finalizing plans for a major strategy shift that will refocus OpenAI around coding and business users.", links=[], newsletter="TLDR AI", date="2026-03-17"),
    StoryRecord(title="Nvidia GTC chips", body="Nvidia introduced new products at GTC, ushering in hardware geared towards running AI models. The company expects to sell $1 trillion worth of Blackwell chips by 2027.", links=[], newsletter="TLDR", date="2026-03-17"),
    StoryRecord(title="Nvidia inference shift", body="Nvidia's focus this year at GTC shifted to inference, the type of computing required to run models. The AI industry is now less concerned with training and more preoccupied with running models.", links=[], newsletter="TLDR AI", date="2026-03-17"),
    StoryRecord(title="Google announces quantum breakthrough", body="Google's quantum computing team announced a new 1000-qubit processor that achieves error correction at scale for the first time.", links=[], newsletter="Tech Digest", date="2026-03-17"),
]

print(f"Input: {len(records)} records")
print(f"Threshold: {settings.dedup_threshold}, Candidate min: {settings.dedup_candidate_min}")

clusters = embed_and_cluster(records)
print(f"Stage 1 clusters: {len(clusters)}")

candidate_pairs = find_candidate_cluster_pairs(
    records, clusters,
    candidate_min=settings.dedup_candidate_min,
    stage1_threshold=settings.dedup_threshold,
)
print(f"Candidate pairs: {candidate_pairs}")

for ci, cj in candidate_pairs:
    r1 = select_representative(clusters[ci])
    r2 = select_representative(clusters[cj])
    print(f"  Pair ({ci},{cj}): '{r1.title}' [{r1.newsletter}] vs '{r2.title}' [{r2.newsletter}]")

representatives = deduplicate(clusters)
print(f"Representatives after Stage 1 dedup: {len(representatives)}")
for r in representatives:
    print(f"  - [{r.source_count} sources] {r.title or '(no title)'[:60]}")
```

Expected output: OpenAI pair and Nvidia pair should appear as candidate clusters or Stage 1 clusters; Google record stays singleton.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `python -c "from config import settings; assert settings.dedup_threshold == 0.65; assert settings.dedup_candidate_min == 0.45; print('config OK')"` prints `config OK`
- [ ] `python -c "from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs; print('embedder OK')"` prints `embedder OK`
- [ ] `python -c "from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative; print('deduplicator OK')"` prints `deduplicator OK`
- [ ] `python -c "from ai.claude_client import filter_stories, confirm_dedup_candidates; print('claude_client OK')"` prints `claude_client OK`
- [ ] `python -c "import processing.digest_builder; print('digest_builder OK')"` prints `digest_builder OK`
- [ ] `python -c "import os; assert not os.path.exists('ai/story_reviewer.py'); print('deleted OK')"` prints `deleted OK`
- [ ] `python -m pytest tests/ -v` — all tests pass, zero failures
- [ ] `python -m pytest tests/test_deduplicator.py -k "merge_confirmed" -v` — 5 new tests pass
- [ ] `python -m pytest tests/test_embedder.py -v` — all new embedder tests pass
- [ ] `python -m pytest tests/test_claude_client.py -v` — all new client tests pass

---

## ROLLBACK CONSIDERATIONS

- `ai/story_reviewer.py` and `tests/test_story_reviewer.py` are deleted. Rollback: restore from git.
- `config.py` changes: revert `dedup_threshold` default to 0.78, remove `dedup_candidate_min`.
- `claude_client.py` and `digest_builder.py` full rewrites: restore from git. The old code was broken (import errors) so rollback returns to a broken state; document this.
- No database schema changes — rollback has no DB impact.
- `.env` files are not changed by this plan.

---

## ACCEPTANCE CRITERIA

- [ ] `settings.dedup_threshold` defaults to 0.65; `settings.dedup_candidate_min` defaults to 0.45
- [ ] `find_candidate_cluster_pairs` returns cross-cluster pairs in [candidate_min, stage1_threshold)
- [ ] `merge_confirmed_clusters` correctly merges confirmed pairs with transitivity
- [ ] `filter_stories` returns `(kept, borderline_flags)` tuple; fail-open on API error
- [ ] `confirm_dedup_candidates` returns `list[bool]`; fail-open (all False) on API error
- [ ] `digest_builder.py` imports cleanly (no `StoryGroup`, no `story_reviewer`)
- [ ] `ai/story_reviewer.py` deleted
- [ ] `tests/test_story_reviewer.py` deleted
- [ ] All validation commands pass with zero errors
- [ ] Full test suite passes (zero failures)
- [ ] No regressions in `test_email_parser.py` or `test_deduplicator.py` existing tests

---

## COMPLETION CHECKLIST

- [ ] All 11 tasks completed in order
- [ ] All Level 1 syntax checks pass
- [ ] Full test suite passes
- [ ] Manual spot-check confirms candidate pair detection works on realistic data
- [ ] `story_reviewer.py` and its test deleted
- [ ] `.env.example` updated

---

## NOTES

### Why not vectorize the candidate pair search?

For N ≤ 100 stories (MVP cap), O(N²) is ~5000 iterations — fast in Python (<100ms). Using tensor operations for the upper-triangle filter would save time but adds complexity and requires `torch` tensor indexing. Kept simple.

### Why fail-open for LLM dedup (all-False)?

A false merge (combining two distinct stories) is worse than a missed dedup (showing a near-duplicate). Fail-open for `confirm_dedup_candidates` keeps stories separate on API failure. Contrast with `filter_stories` which also fails open (keep all) because false drops are unrecoverable.

### Representative selection for candidate groups

`select_representative` is called on each cluster to pick the best story to show the LLM. This uses the same priority (longest body → has title → has links) as the final dedup step. The LLM sees the best version of each cluster, not all items.

### `generate_digest` removed

The old `claude_client.py` had `generate_digest` which produced `headline`, `summary`, `significance` fields. Per CLAUDE.md (updated architecture): "No AI generation. The pipeline extracts and selects — it does not rewrite, summarize, or produce generated content." The response now returns `StoryRecord` fields directly: `{title, body, link, links, newsletter, date, source_count}`.

### Source count in response

`source_count` on each story indicates how many newsletter sources covered it (set by `select_representative`). This is useful for the frontend to indicate "covered by 3 sources".

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `python -c "from config import settings; assert settings.dedup_threshold == 0.65; assert settings.dedup_candidate_min == 0.45; print('config OK')"`
  Expected output or result:
  `config OK`

- Item to check:
  `python -c "from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs; print('embedder OK')"`
  Expected output or result:
  `embedder OK`

- Item to check:
  `python -c "from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative; print('deduplicator OK')"`
  Expected output or result:
  `deduplicator OK`

- Item to check:
  `python -c "from ai.claude_client import filter_stories, confirm_dedup_candidates; print('claude_client OK')"`
  Expected output or result:
  `claude_client OK`

- Item to check:
  `python -c "import processing.digest_builder; print('digest_builder OK')"`
  Expected output or result:
  `digest_builder OK`

- Item to check:
  `python -c "import os; assert not os.path.exists('ai/story_reviewer.py'); print('deleted OK')"`
  Expected output or result:
  `deleted OK`

- Item to check:
  `python -m pytest tests/ -v`
  Expected output or result:
  All tests pass. Zero failures. Summary line shows N passed in Xs.

- Item to check:
  `python -m pytest tests/test_deduplicator.py -k "merge_confirmed" -v`
  Expected output or result:
  5 tests collected and passed. PASSED for each of: test_merge_confirmed_no_pairs_returns_original, test_merge_confirmed_single_pair, test_merge_confirmed_transitivity, test_merge_confirmed_unconfirmed_clusters_preserved, test_merge_confirmed_multi_item_clusters.

- Item to check:
  `python -m pytest tests/test_embedder.py -v`
  Expected output or result:
  All tests in test_embedder.py collected and passed.

- Item to check:
  `python -m pytest tests/test_claude_client.py -v`
  Expected output or result:
  All tests in test_claude_client.py collected and passed. Zero failures (no StoryGroup or StoryChunk import errors).
