# Feature: pipeline-noise-filter-and-pairwise-dedup

The following plan should be complete, but it's important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils, types, and models. Import from the right files.

## Feature Description

Restructure the deduplication pipeline with three coordinated changes:

1. **Pre-cluster LLM noise filter** — a new LLM step inserted immediately after parsing that removes obvious structural non-article content (sponsor blocks, referral prompts, newsletter intros/outros, polls, CTAs, subscription text) before embedding. This prevents noise from contaminating candidate generation. Maximally conservative: only removes content that is *unambiguously* not an article.

2. **Single-threshold embedding + pairwise LLM dedup** — replaces the current two-threshold band approach (`find_candidate_cluster_pairs` + `confirm_dedup_candidates` boolean) with a single modestly-lower threshold (0.55) for high-recall candidate grouping, followed by pairwise LLM comparison *within* each multi-story cluster. The LLM makes a three-way decision per pair: `same_story`, `related_but_distinct`, or `different`. Only `same_story` pairs are merged. This allows accurate deduplication across newsletters regardless of writing style differences, while correctly preserving stories that cover different developments from the same company or event.

3. **Preserved Stage 6 editorial filter** — the existing `filter_stories` function and Stage 6 of the pipeline remain unchanged. That step is editorial selection on the final deduplicated output; it is distinct from the noise filter.

## User Story

As a newsletter digest user,
I want the digest to correctly identify and merge duplicate stories across different newsletters even when they are written in different styles,
So that I see each real news item exactly once, and stories about different developments are always shown separately.

## Problem Statement

The current pipeline fails in two ways:
- Structural noise (sponsor blocks, intros/outros, CTAs) participates in embedding and clustering, creating spurious similarity signals that pollute candidate generation.
- The two-threshold hybrid dedup (0.45–0.65 band) cannot distinguish between "same story written differently" and "related stories about different developments from the same company/event." The boolean `same_story` field has no way to express the `related_but_distinct` case, causing false merges when two Nvidia stories or two OpenAI stories land in the same cluster.

## Scope

- **In scope**: config changes, embedder cleanup, two new LLM functions in `claude_client.py`, updated pipeline in `digest_builder.py`, updated tests
- **Out of scope**: changes to `email_parser.py`, `deduplicator.py`, `select_representative`, `deduplicate`, `merge_confirmed_clusters`, Stage 6 `filter_stories`, database, API routes, frontend

## Solution Statement

Insert a conservative LLM noise filter between parsing and embedding. Remove `find_candidate_cluster_pairs`. Lower the embedding threshold to 0.55. Add `refine_clusters()` that works *within* each multi-story cluster to apply pairwise LLM comparison with three-way classification, using union-find to produce final merged sub-groups. `merge_confirmed_clusters` is retained (it stays in `deduplicator.py`) but is no longer called in the main pipeline — the union-find logic now lives inside `refine_clusters`.

## Feature Metadata

**Feature Type**: Enhancement / Refactor
**Estimated Complexity**: Medium
**Primary Systems Affected**: `ai/claude_client.py`, `processing/embedder.py`, `processing/digest_builder.py`, `config.py`, test files
**Dependencies**: anthropic SDK (already used), sentence-transformers (already used)
**Assumptions**:
- `merge_confirmed_clusters` stays in `deduplicator.py` but is not called in the main pipeline after this change — it can be kept as a utility
- Fail-open for `filter_noise`: on API error, return all stories unchanged
- Fail-open for `refine_clusters`: on API error or count mismatch, return input clusters unchanged (trust embedding result)
- Threshold 0.55 is a starting point; it will be tuned after real runs

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `ai/claude_client.py` (entire file) — Pattern source for all new LLM functions. Mirror the lazy client init (`lines 18–24`), tool schema dict structure (`lines 33–68`), system prompt function (`lines 71–92`), `_build_*_message` helper (`lines 95–110`), async batching loop with fail-open (`lines 113–220`). The `confirm_dedup_candidates` section (`lines 223–372`) is the function being **replaced** — read it to understand what to remove.

- `processing/embedder.py` (entire file) — `embed_and_cluster` (`lines 34–71`) stays unchanged. `find_candidate_cluster_pairs` (`lines 74–130`) is **removed entirely**.

- `processing/deduplicator.py` (`lines 55–113`) — `merge_confirmed_clusters` contains the union-find pattern with path compression that `refine_clusters` must replicate internally. Read carefully — the same logic is reused inside the new function.

- `processing/digest_builder.py` (entire file) — Full pipeline to be rewritten. Current 6-stage structure is the pattern to follow for logging, error handling, and stage numbering.

- `config.py` (entire file) — `dedup_candidate_min` field removed, `dedup_threshold` default changed.

- `tests/test_claude_client.py` (entire file) — Test pattern for constants, schema validation, message building. Keep all 9 `filter_stories` tests. Replace 6 dedup tests with noise + refine tests.

- `tests/test_embedder.py` (entire file) — All 6 tests cover `find_candidate_cluster_pairs` which is removed. Replace with `embed_and_cluster` smoke tests.

### New Files to Create

None. All changes are to existing files.

### Files Modified

- `config.py`
- `.env`
- `.env.example`
- `processing/embedder.py`
- `ai/claude_client.py`
- `processing/digest_builder.py`
- `tests/test_embedder.py`
- `tests/test_claude_client.py`

### Patterns to Follow

**Lazy client init** (`claude_client.py:18–24`):
```python
_client: AsyncAnthropic | None = None

def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        logger.info("Initializing AsyncAnthropic client (model=%s)", settings.claude_model)
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client
```

**Tool schema dict** (`claude_client.py:33–68`): name, description, input_schema with type/properties/required.

**Async batching loop with fail-open** (`claude_client.py:147–218`):
```python
for batch_num, batch in enumerate(batches, 1):
    try:
        response = await client.messages.create(...)
    except anthropic.APIError as exc:
        logger.error("... — keeping all", batch_num, ..., exc)
        # fail-open: extend results and continue
        continue
    # extract tool_use block
    # count-mismatch guard → fail-open
    # process decisions
```

**Union-find with path compression** (`deduplicator.py:78–97`):
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

**Pipeline stage logging** (`digest_builder.py:72–131`):
```python
logger.info("Stage X/6 — Description")
...
logger.info("Stage X/6 — Result: %d item(s)", n)
```

**Naming conventions**:
- Constants: `_UPPER_SNAKE_CASE` module-level
- Private helpers: `_lower_snake_case`
- Public async functions: `async def lower_snake_case`
- All new functions in `claude_client.py` follow the `_TOOL_NAME / _TOOL_SCHEMA / _BATCH_SIZE / _MAX_BODY_CHARS / _build_message / async function` grouping pattern

---

## IMPLEMENTATION PLAN

### Phase 1: Foundation (config + embedder cleanup)

Remove the old two-threshold config field, lower the main threshold, remove `find_candidate_cluster_pairs` from the embedder. These are prerequisites for all later steps.

### Phase 2: Core LLM Functions

Add `filter_noise` and `refine_clusters` to `claude_client.py`. Remove `confirm_dedup_candidates` and its supporting constants/helpers.

### Phase 3: Pipeline Integration

Update `digest_builder.py` to wire in the new 6-stage pipeline.

### Phase 4: Tests

Update `test_embedder.py` and `test_claude_client.py` to cover new functionality and remove deleted functions.

---

## STEP-BY-STEP TASKS

### Task 1: UPDATE `config.py`

- **REMOVE**: `dedup_candidate_min: float = 0.45` field
- **UPDATE**: `dedup_threshold: float = 0.65` → `dedup_threshold: float = 0.55`
- **GOTCHA**: pydantic-settings reads from `.env` which overrides the default — `.env` must also be updated (Task 2) or validation will fail
- **VALIDATE**: `python -c "from config import settings; assert settings.dedup_threshold == 0.55; assert not hasattr(settings, 'dedup_candidate_min'); print('OK')"`

### Task 2: UPDATE `.env` and `.env.example`

**`.env`**:
- **UPDATE**: `DEDUP_THRESHOLD=0.65` → `DEDUP_THRESHOLD=0.55`
- **REMOVE**: `DEDUP_CANDIDATE_MIN=0.45` line and its comment block

**`.env.example`**:
- **UPDATE**: `DEDUP_THRESHOLD=0.65` → `DEDUP_THRESHOLD=0.55`
- **REMOVE**: `DEDUP_CANDIDATE_MIN=0.45` line
- **UPDATE**: comment block above `DEDUP_THRESHOLD` to reflect new single-threshold design:
  - Remove all references to `DEDUP_CANDIDATE_MIN` and the two-band approach
  - New description: "DEDUP_THRESHOLD: cosine similarity threshold for embedding-based candidate grouping. Stories above this threshold are placed in the same candidate cluster for LLM pairwise review. Default 0.55 provides high recall; tune up if clusters are too large."
- **GOTCHA**: `.env` has real credentials — only edit the DEDUP lines, do not touch IMAP/API/DB/Server values
- **VALIDATE**: `python -c "from config import settings; assert settings.dedup_threshold == 0.55; print('OK')"`

### Task 3: UPDATE `processing/embedder.py`

- **REMOVE**: entire `find_candidate_cluster_pairs` function (`lines 74–130`)
- **REMOVE**: associated imports used only by that function — check whether `st_util.cos_sim` is used only in `find_candidate_cluster_pairs`; if so, `st_util` import stays (it's also used in `community_detection` indirectly via the same module)
- **KEEP**: `embed_and_cluster` unchanged
- **KEEP**: all existing imports (`SentenceTransformer`, `st_util`, `settings`, `StoryRecord`, `logger`)
- **GOTCHA**: `st_util` is used in `embed_and_cluster` via `community_detection` which is `st_util.community_detection` — do not remove the import even though `cos_sim` is no longer called
- **VALIDATE**: `python -c "from processing.embedder import embed_and_cluster; from processing import embedder; assert not hasattr(embedder, 'find_candidate_cluster_pairs'); print('OK')"`

### Task 4: UPDATE `ai/claude_client.py`

This is the largest task. Make all changes in order.

#### 4a. ADD `filter_noise` function group

Insert **before** the existing `filter_stories` section (i.e., near the top after `_get_client`). Add the following constants, schema, system prompt, message builder, and async function:

**Constants**:
```python
_NOISE_TOOL_NAME = "filter_noise"
_NOISE_BATCH_SIZE = 30
_NOISE_MAX_BODY_CHARS = 200
```

**Tool schema** (`_NOISE_TOOL_SCHEMA`):
```python
_NOISE_TOOL_SCHEMA: dict = {
    "name": _NOISE_TOOL_NAME,
    "description": (
        "Classify each item as ARTICLE or NOISE. "
        "Only mark as NOISE when the item is clearly non-article structural content. "
        "When uncertain, classify as ARTICLE."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per item, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "is_noise": {
                            "type": "boolean",
                            "description": (
                                "True = NOISE (remove). False = ARTICLE (keep). "
                                "Default to False when uncertain."
                            ),
                        },
                    },
                    "required": ["is_noise"],
                },
            }
        },
        "required": ["decisions"],
    },
}
```

**System prompt** (`_NOISE_SYSTEM_PROMPT`):
```python
_NOISE_SYSTEM_PROMPT = (
    "You are a pre-processing filter for a newsletter digest pipeline. "
    "Your only job is to remove obvious structural noise before content analysis.\n\n"
    "Mark is_noise=True ONLY for items that are clearly non-article structural content:\n"
    "- Sponsor or referral blocks: 'Refer 3 friends to unlock...', 'Sponsored by X'\n"
    "- Newsletter infrastructure: subscribe/unsubscribe prompts, account management\n"
    "- Pure CTAs with no substantive information: 'Click here', 'Sign up today'\n"
    "- Newsletter intro/outro shells with no article content: "
    "'Welcome to today's issue', 'That's all for this week'\n"
    "- Polls and surveys with no article text: 'How did we do? Vote below'\n\n"
    "Mark is_noise=False (KEEP) for everything else, including:\n"
    "- Any real article, news item, announcement, or report — even if short or low quality\n"
    "- Any item that contains substantive information, even if it is also promotional\n"
    "- Job listings, product launches, research summaries, event notices\n"
    "- Sponsor content that explains a real product, service, or offer in detail\n"
    "- Anything ambiguous — when in doubt, always keep\n\n"
    "This filter is maximally conservative. It is better to keep 10 noisy items "
    "than to accidentally remove one real article."
)
```

**Message builder** (`_build_noise_message`):
```python
def _build_noise_message(stories: list[StoryRecord]) -> str:
    lines: list[str] = [
        f"Below are {len(stories)} item(s) extracted from newsletters. "
        "Classify each as ARTICLE or NOISE.\n"
    ]
    for i, story in enumerate(stories, 1):
        lines.append(f"## Item {i}")
        if story.title:
            lines.append(f"Title: {story.title}")
        lines.append(f"Newsletter: {story.newsletter}")
        lines.append(f"Body: {story.body[:_NOISE_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_NOISE_TOOL_NAME}` tool to return {len(stories)} decisions "
        f"(is_noise) in the same order."
    )
    return "\n".join(lines)
```

**Async function** (`filter_noise`):
```python
async def filter_noise(stories: list[StoryRecord]) -> list[StoryRecord]:
    """Pre-cluster noise filter. Removes obvious structural non-article content.

    Runs before embedding. Maximally conservative — only removes items that are
    unambiguously structural noise (sponsor blocks, referral prompts, intro/outro
    shells, polls, subscription text). Never removes real articles, even if short.

    Args:
        stories: All StoryRecord objects from parse_emails().

    Returns:
        Filtered list. On API failure, returns input list unchanged (fail-open).
    """
    if not stories:
        return []

    client = _get_client()
    batches = [stories[i:i + _NOISE_BATCH_SIZE] for i in range(0, len(stories), _NOISE_BATCH_SIZE)]

    logger.info(
        "LLM noise filter: %d item(s) in %d batch(es)",
        len(stories),
        len(batches),
    )

    kept: list[StoryRecord] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_noise_message(batch)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                system=_NOISE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[_NOISE_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _NOISE_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error(
                "LLM noise filter API error on batch %d/%d: %s — keeping all",
                batch_num, len(batches), exc,
            )
            kept.extend(batch)
            continue

        logger.debug(
            "LLM noise filter batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning(
                "LLM noise filter batch %d/%d: no tool_use block — keeping all %d",
                batch_num, len(batches), len(batch),
            )
            kept.extend(batch)
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM noise filter batch %d/%d: count mismatch (%d decisions for %d items) — keeping all",
                batch_num, len(batches), len(decisions), len(batch),
            )
            kept.extend(batch)
            continue

        batch_kept = 0
        batch_removed = 0
        for story, decision in zip(batch, decisions):
            if not decision.get("is_noise", False):
                kept.append(story)
                batch_kept += 1
            else:
                batch_removed += 1

        logger.info(
            "LLM noise filter batch %d/%d: kept %d / %d (removed %d as noise)",
            batch_num, len(batches), batch_kept, len(batch), batch_removed,
        )

    return kept
```

#### 4b. ADD `refine_clusters` function group

Insert **after** `filter_noise` and **before** `filter_stories`. Add the following:

**Constants**:
```python
_REFINE_TOOL_NAME = "refine_clusters"
_REFINE_BATCH_SIZE = 20
_REFINE_MAX_BODY_CHARS = 250
```

**Tool schema** (`_REFINE_TOOL_SCHEMA`):
```python
_REFINE_TOOL_SCHEMA: dict = {
    "name": _REFINE_TOOL_NAME,
    "description": (
        "For each story pair, classify the relationship between the two stories. "
        "Return one decision per pair, in input order."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per pair, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "relationship": {
                            "type": "string",
                            "enum": ["same_story", "related_but_distinct", "different"],
                            "description": (
                                "'same_story': both stories cover the same specific event, "
                                "announcement, or development — merge them. "
                                "'related_but_distinct': same company/topic but different "
                                "developments or announcements — keep separate. "
                                "'different': unrelated stories — keep separate."
                            ),
                        },
                    },
                    "required": ["relationship"],
                },
            }
        },
        "required": ["decisions"],
    },
}
```

**System prompt** (`_REFINE_SYSTEM_PROMPT`):
```python
_REFINE_SYSTEM_PROMPT = (
    "You are a deduplication assistant for a newsletter digest. "
    "You will be shown pairs of story excerpts from different newsletters that "
    "scored above the embedding similarity threshold.\n\n"
    "For each pair, classify the relationship:\n\n"
    "'same_story' — Both stories cover the SAME specific event, announcement, or "
    "development. The underlying news item is identical even if the writing style, "
    "length, or framing differs. Example: TLDR says 'OpenAI released GPT-5 today' "
    "and The Deep View says 'OpenAI unveils GPT-5 with enhanced reasoning' — same story.\n\n"
    "'related_but_distinct' — The stories are about the same company, topic, or event "
    "series, but describe DIFFERENT specific developments. Example: one story covers "
    "Nvidia's new GPU announcement at GTC and another covers Nvidia's inference "
    "cost reduction strategy — related but different news items.\n\n"
    "'different' — The stories are about unrelated topics.\n\n"
    "Key rule: only use 'same_story' when both stories are clearly reporting the same "
    "specific news item. When in doubt, use 'related_but_distinct' or 'different'. "
    "It is better to show a near-duplicate than to hide a distinct story."
)
```

**Message builder** (`_build_refine_message`):
```python
def _build_refine_message(pairs: list[tuple[StoryRecord, StoryRecord]]) -> str:
    lines: list[str] = [
        f"Below are {len(pairs)} story pair(s) from different newsletters. "
        "Classify the relationship between the stories in each pair.\n"
    ]
    for i, (story_a, story_b) in enumerate(pairs, 1):
        lines.append(f"## Pair {i}")
        lines.append(f"Story A (from {story_a.newsletter}):")
        if story_a.title:
            lines.append(f"  Title: {story_a.title}")
        lines.append(f"  Body: {story_a.body[:_REFINE_MAX_BODY_CHARS]}")
        lines.append(f"Story B (from {story_b.newsletter}):")
        if story_b.title:
            lines.append(f"  Title: {story_b.title}")
        lines.append(f"  Body: {story_b.body[:_REFINE_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_REFINE_TOOL_NAME}` tool to return {len(pairs)} decisions "
        "(relationship: same_story | related_but_distinct | different) in the same order."
    )
    return "\n".join(lines)
```

**Async function** (`refine_clusters`):
```python
async def refine_clusters(
    clusters: list[list[StoryRecord]],
) -> list[list[StoryRecord]]:
    """LLM pairwise dedup refinement within each candidate cluster.

    For each cluster with more than one story, generates all pairwise comparisons
    and asks the LLM to classify each pair as same_story, related_but_distinct,
    or different. Only same_story pairs are merged (via union-find). Clusters that
    contained only related or different stories are split into singletons.

    Args:
        clusters: Candidate clusters from embed_and_cluster(). Singletons pass through.

    Returns:
        Refined cluster list. Same_story groups become single clusters; unconfirmed
        stories are returned as singletons. On API failure or count mismatch, the
        input clusters are returned unchanged (fail-open: trust embedding result).
    """
    if not clusters:
        return []

    # Collect all pairwise comparisons across multi-story clusters
    # Track: (cluster_index, story_index_i, story_index_j) → pair position in flat list
    all_pairs: list[tuple[StoryRecord, StoryRecord]] = []
    pair_origins: list[tuple[int, int, int]] = []  # (cluster_idx, story_i, story_j)

    for c_idx, cluster in enumerate(clusters):
        if len(cluster) < 2:
            continue
        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                all_pairs.append((cluster[i], cluster[j]))
                pair_origins.append((c_idx, i, j))

    if not all_pairs:
        return clusters[:]

    client = _get_client()
    batches = [all_pairs[k:k + _REFINE_BATCH_SIZE] for k in range(0, len(all_pairs), _REFINE_BATCH_SIZE)]

    logger.info(
        "LLM cluster refinement: %d pair(s) across %d multi-story cluster(s) in %d batch(es)",
        len(all_pairs),
        sum(1 for c in clusters if len(c) >= 2),
        len(batches),
    )

    # Collect LLM decisions for all pairs; None = not yet decided (fail-open fallback)
    pair_decisions: list[str | None] = [None] * len(all_pairs)
    pair_offset = 0

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_refine_message(batch)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                system=_REFINE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[_REFINE_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _REFINE_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error(
                "LLM cluster refinement API error on batch %d/%d: %s — keeping clusters unchanged",
                batch_num, len(batches), exc,
            )
            pair_offset += len(batch)
            continue

        logger.debug(
            "LLM cluster refinement batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning(
                "LLM cluster refinement batch %d/%d: no tool_use block — keeping clusters unchanged",
                batch_num, len(batches),
            )
            pair_offset += len(batch)
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM cluster refinement batch %d/%d: count mismatch (%d decisions for %d pairs) — keeping clusters unchanged",
                batch_num, len(batches), len(decisions), len(batch),
            )
            pair_offset += len(batch)
            continue

        batch_same = 0
        for k, decision in enumerate(decisions):
            rel = decision.get("relationship", "different")
            pair_decisions[pair_offset + k] = rel
            if rel == "same_story":
                batch_same += 1

        logger.info(
            "LLM cluster refinement batch %d/%d: %d/%d pairs classified as same_story",
            batch_num, len(batches), batch_same, len(batch),
        )
        pair_offset += len(batch)

    # Apply union-find per cluster based on same_story decisions
    # For pairs where decision is None (API failure), treat cluster as-is
    # Build: for each cluster, collect which pairs were decided
    from collections import defaultdict
    cluster_same_pairs: dict[int, list[tuple[int, int]]] = defaultdict(list)

    for pair_idx, (c_idx, i, j) in enumerate(pair_origins):
        if pair_decisions[pair_idx] == "same_story":
            cluster_same_pairs[c_idx].append((i, j))

    # Check if any cluster had undecided pairs (API failure) — keep that cluster intact
    cluster_had_failure: set[int] = set()
    for pair_idx, (c_idx, i, j) in enumerate(pair_origins):
        if pair_decisions[pair_idx] is None:
            cluster_had_failure.add(c_idx)

    result: list[list[StoryRecord]] = []

    for c_idx, cluster in enumerate(clusters):
        if len(cluster) < 2:
            result.append(cluster)
            continue

        if c_idx in cluster_had_failure:
            # API failure for this cluster's pairs — return cluster intact
            result.append(cluster)
            continue

        # Union-find within this cluster
        n = len(cluster)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i, j in cluster_same_pairs[c_idx]:
            union(i, j)

        # Group stories by root
        groups: dict[int, list[StoryRecord]] = defaultdict(list)
        for story_idx, story in enumerate(cluster):
            groups[find(story_idx)].append(story)

        for sub_cluster in groups.values():
            result.append(sub_cluster)

    same_count = sum(len(v) for v in cluster_same_pairs.values())
    logger.info(
        "LLM cluster refinement: %d same_story pair(s) confirmed → %d cluster(s) (was %d)",
        same_count,
        len(result),
        len(clusters),
    )
    return result
```

#### 4c. REMOVE `confirm_dedup_candidates` and its supporting code

Remove the entire section from `# ── confirm_dedup_candidates` to end of file (`lines 223–372`):
- `_DEDUP_TOOL_NAME`
- `_DEDUP_BATCH_SIZE`
- `_DEDUP_MAX_BODY_CHARS`
- `_DEDUP_TOOL_SCHEMA`
- `_DEDUP_SYSTEM_PROMPT`
- `_build_dedup_message`
- `confirm_dedup_candidates`

- **VALIDATE**:
```bash
python -c "
from ai.claude_client import (
    _NOISE_TOOL_NAME, _NOISE_TOOL_SCHEMA, _NOISE_BATCH_SIZE,
    _REFINE_TOOL_NAME, _REFINE_TOOL_SCHEMA, _REFINE_BATCH_SIZE,
    filter_noise, refine_clusters, filter_stories,
)
from ai import claude_client
assert not hasattr(claude_client, 'confirm_dedup_candidates')
assert not hasattr(claude_client, '_DEDUP_TOOL_SCHEMA')
print('claude_client imports OK')
"
```

### Task 5: UPDATE `processing/digest_builder.py`

Full rewrite of imports and pipeline. The pipeline becomes 6 stages (parse, noise_filter, embed, refine, dedup, editorial).

**Imports to add**:
```python
from ai.claude_client import filter_noise, filter_stories, refine_clusters
```

**Imports to remove**:
```python
# Remove: confirm_dedup_candidates
# Remove: find_candidate_cluster_pairs
# Remove: merge_confirmed_clusters (no longer called in main pipeline)
# Remove: select_representative (only used inside deduplicate, not needed in digest_builder)
```

Wait — check current imports carefully. Current `digest_builder.py` imports:
```python
from ai.claude_client import confirm_dedup_candidates, filter_stories
from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative
from processing.embedder import embed_and_cluster, find_candidate_cluster_pairs
```

New imports should be:
```python
from ai.claude_client import filter_noise, filter_stories, refine_clusters
from processing.deduplicator import deduplicate
from processing.embedder import embed_and_cluster
```

**New 6-stage pipeline** inside `build_digest`:

```
Stage 1/6 — Fetch emails
Stage 2/6 — Parse emails
Stage 3/6 — LLM noise filter  (NEW)
Stage 4/6 — Embed + cluster
Stage 5/6 — LLM pairwise dedup refinement  (NEW, replaces candidate pairs + confirm)
Stage 6/6 — Deduplicate → representatives
Stage 7/6 — ... wait, we now have 7 stages
```

Actually it's now 7 stages total. Renumber:

```
Stage 1/7 — Fetch emails
Stage 2/7 — Parse emails
Stage 3/7 — LLM noise filter (NEW)
Stage 4/7 — Embed + cluster
Stage 5/7 — LLM pairwise dedup refinement (NEW)
Stage 6/7 — Deduplicate → representatives
Stage 7/7 — LLM editorial filter
```

**Stage 3 code**:
```python
logger.info("Stage 3/7 — Running LLM noise filter on %d parsed item(s)", len(story_records))
story_records = await filter_noise(story_records)
noise_removed = ... (track count before/after)
logger.info("Stage 3/7 — %d item(s) after noise filter (%d removed)", len(story_records), noise_removed)
```

Track count: save `before_noise = len(story_records)` before the call, then `noise_removed = before_noise - len(story_records)`.

**Stage 5 code**:
```python
logger.info("Stage 5/7 — LLM pairwise dedup refinement on %d cluster(s)", len(clusters))
clusters = await refine_clusters(clusters)
logger.info("Stage 5/7 — %d cluster(s) after refinement", len(clusters))
```

**Complete new pipeline**:
```python
# Stage 1/7: Fetch emails
# Stage 2/7: Parse emails
# Stage 3/7: LLM noise filter
# Stage 4/7: Embed + cluster
# Stage 5/7: LLM pairwise dedup refinement
# Stage 6/7: Deduplicate → representatives
# Stage 7/7: LLM editorial filter (filter_stories) — unchanged
```

The `response` dict and DB persistence code remain unchanged.

- **VALIDATE**:
```bash
python -c "
import inspect
from processing import digest_builder
src = inspect.getsource(digest_builder)
assert 'filter_noise' in src
assert 'refine_clusters' in src
assert 'Stage 3/7' in src
assert 'Stage 7/7' in src
assert 'confirm_dedup_candidates' not in src
assert 'find_candidate_cluster_pairs' not in src
assert 'merge_confirmed_clusters' not in src
print('digest_builder OK')
"
```

### Task 6: UPDATE `tests/test_embedder.py`

**REMOVE**: All 6 existing tests (they all test `find_candidate_cluster_pairs` which is deleted).

**ADD**: 6 smoke tests for `embed_and_cluster`:

```python
from processing.embedder import embed_and_cluster

def test_embed_and_cluster_empty_input():
    """Empty input → empty output."""
    assert embed_and_cluster([]) == []

def test_embed_and_cluster_single_item():
    """Single item → one singleton cluster."""
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
```

- **VALIDATE**: `python -m pytest tests/test_embedder.py -v`

### Task 7: UPDATE `tests/test_claude_client.py`

**KEEP**: All 9 existing `filter_stories` tests (lines 26–89 of current file). Do not change them.

**REMOVE**: All 6 dedup tests (`test_dedup_batch_size`, `test_dedup_tool_name`, `test_dedup_schema_same_story_field`, `test_dedup_message_labels_stories_with_newsletter`, `test_dedup_message_group_count_matches`, `test_dedup_batch_split_50_groups`).

**REMOVE**: Old imports from the import block:
```python
# Remove:
_DEDUP_BATCH_SIZE,
_DEDUP_TOOL_NAME,
_DEDUP_TOOL_SCHEMA,
_build_dedup_message,
```

**ADD**: New imports:
```python
from ai.claude_client import (
    _FILTER_BATCH_SIZE,
    _FILTER_TOOL_NAME,
    _FILTER_TOOL_SCHEMA,
    _FILTER_MAX_BODY_CHARS,
    _build_filter_message,
    _NOISE_BATCH_SIZE,
    _NOISE_TOOL_NAME,
    _NOISE_TOOL_SCHEMA,
    _NOISE_MAX_BODY_CHARS,
    _build_noise_message,
    _REFINE_BATCH_SIZE,
    _REFINE_TOOL_NAME,
    _REFINE_TOOL_SCHEMA,
    _build_refine_message,
)
```

**ADD**: 7 noise filter tests:

```python
# ── filter_noise constants ─────────────────────────────────────────────────────

def test_noise_batch_size():
    """_NOISE_BATCH_SIZE is 30."""
    assert _NOISE_BATCH_SIZE == 30

def test_noise_tool_name():
    """_NOISE_TOOL_NAME matches schema name."""
    assert _NOISE_TOOL_SCHEMA["name"] == _NOISE_TOOL_NAME

def test_noise_schema_is_noise_field():
    """Noise tool schema has decisions array with is_noise boolean field."""
    items = _NOISE_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    assert "is_noise" in items["properties"]
    assert items["properties"]["is_noise"]["type"] == "boolean"

def test_noise_batch_split_95_stories():
    """95 stories split into ceil(95/30) = 4 batches: 30, 30, 30, 5."""
    stories = list(range(95))
    batches = [stories[i:i + _NOISE_BATCH_SIZE] for i in range(0, len(stories), _NOISE_BATCH_SIZE)]
    assert len(batches) == 4
    assert len(batches[0]) == 30
    assert len(batches[1]) == 30
    assert len(batches[2]) == 30
    assert len(batches[3]) == 5

def test_noise_message_includes_newsletter_name():
    """Noise message includes the newsletter name for each item."""
    story = _record("This is an article about OpenAI.", newsletter="TLDR AI")
    msg = _build_noise_message([story])
    assert "TLDR AI" in msg

def test_noise_message_includes_body_excerpt():
    """Noise message includes body text."""
    story = _record("This is the body content of a real article.")
    msg = _build_noise_message([story])
    assert "This is the body content" in msg

def test_noise_message_truncates_long_body():
    """Noise message truncates body to _NOISE_MAX_BODY_CHARS."""
    long_body = "X" * (_NOISE_MAX_BODY_CHARS + 100)
    story = _record(long_body)
    msg = _build_noise_message([story])
    assert "X" * (_NOISE_MAX_BODY_CHARS + 100) not in msg
```

**ADD**: 6 refine cluster tests:

```python
# ── refine_clusters constants ──────────────────────────────────────────────────

def test_refine_batch_size():
    """_REFINE_BATCH_SIZE is 20."""
    assert _REFINE_BATCH_SIZE == 20

def test_refine_tool_name():
    """_REFINE_TOOL_NAME matches schema name."""
    assert _REFINE_TOOL_SCHEMA["name"] == _REFINE_TOOL_NAME

def test_refine_schema_relationship_enum():
    """Refine tool schema has decisions array with relationship enum field."""
    items = _REFINE_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    assert "relationship" in items["properties"]
    assert items["properties"]["relationship"]["type"] == "string"

def test_refine_relationship_enum_values():
    """Relationship enum contains exactly the three required values."""
    items = _REFINE_TOOL_SCHEMA["input_schema"]["properties"]["decisions"]["items"]
    enum_values = items["properties"]["relationship"]["enum"]
    assert set(enum_values) == {"same_story", "related_but_distinct", "different"}

def test_refine_message_labels_newsletter():
    """Refine message labels each story with its newsletter name."""
    r1 = _record("OpenAI released GPT-5.", newsletter="TLDR")
    r2 = _record("OpenAI unveiled GPT-5 this week.", newsletter="The Deep View")
    msg = _build_refine_message([(r1, r2)])
    assert "TLDR" in msg
    assert "The Deep View" in msg

def test_refine_batch_split_45_pairs():
    """45 pairs split into ceil(45/20) = 3 batches: 20, 20, 5."""
    pairs = list(range(45))
    batches = [pairs[i:i + _REFINE_BATCH_SIZE] for i in range(0, len(pairs), _REFINE_BATCH_SIZE)]
    assert len(batches) == 3
    assert len(batches[0]) == 20
    assert len(batches[1]) == 20
    assert len(batches[2]) == 5
```

- **VALIDATE**: `python -m pytest tests/test_claude_client.py -v`

---

## TESTING STRATEGY

### Unit Tests

All tests are in `tests/` with no mocking framework. Tests that call real sentence-transformers are integration-level (acceptable: model is local, ~0.5s per test on first load). No live Claude API calls in tests — only structural/schema/message-building tests.

**test_embedder.py** — 6 tests covering `embed_and_cluster` (empty, single, identical, unrelated, completeness, no-duplicates)

**test_claude_client.py** — 22 tests total:
- 9 existing `filter_stories` tests (unchanged)
- 7 new `filter_noise` tests
- 6 new `refine_clusters` tests

**test_deduplicator.py** — 27 tests (unchanged — `merge_confirmed_clusters`, `select_representative`, `deduplicate` untouched)

**test_email_parser.py** — unchanged

### Integration Tests

No changes to pipeline integration tests (none currently exist). Manual spot-check covers integration.

### Edge Cases

- `filter_noise` with empty input → return `[]`
- `refine_clusters` with all singleton clusters → return input unchanged (no pairs generated)
- `refine_clusters` with all `related_but_distinct` pairs → all singletons returned
- `refine_clusters` with all `same_story` pairs in a 3-story cluster → one merged cluster (transitivity via union-find)
- API failure on any batch → fail-open behavior (keep all for noise, keep clusters unchanged for refine)

---

## VALIDATION COMMANDS

### Level 1: Syntax & Imports

```bash
python -c "
from config import settings
from processing.embedder import embed_and_cluster
from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative
from ai.claude_client import filter_noise, filter_stories, refine_clusters
from processing.digest_builder import build_digest
from ai import claude_client
from processing import embedder
assert not hasattr(claude_client, 'confirm_dedup_candidates'), 'confirm_dedup_candidates not removed'
assert not hasattr(claude_client, '_DEDUP_TOOL_SCHEMA'), '_DEDUP_TOOL_SCHEMA not removed'
assert not hasattr(embedder, 'find_candidate_cluster_pairs'), 'find_candidate_cluster_pairs not removed'
assert not hasattr(settings, 'dedup_candidate_min'), 'dedup_candidate_min not removed from config'
assert settings.dedup_threshold == 0.55, f'Expected 0.55, got {settings.dedup_threshold}'
print('All imports and config OK')
"
```

### Level 2: Unit Tests

```bash
python -m pytest tests/test_embedder.py tests/test_claude_client.py tests/test_deduplicator.py -v
```

### Level 3: Full Test Suite

```bash
python -m pytest tests/ -v
```

### Level 4: Manual Spot-Check

```bash
python -c "
from ingestion.email_parser import StoryRecord
from processing.embedder import embed_and_cluster

records = [
    StoryRecord(title=None, body='OpenAI released GPT-5 today with major reasoning improvements.', links=[], newsletter='TLDR AI', date='2026-04-07'),
    StoryRecord(title=None, body='OpenAI unveils GPT-5 featuring enhanced reasoning capabilities.', links=[], newsletter='The Deep View', date='2026-04-07'),
    StoryRecord(title=None, body='Nvidia announced new GTC datacenter chips with improved performance.', links=[], newsletter='TLDR', date='2026-04-07'),
    StoryRecord(title=None, body='Nvidia shifts strategy to inference cost reduction for enterprise.', links=[], newsletter='TLDR AI', date='2026-04-07'),
    StoryRecord(title=None, body='Google announces quantum computing breakthrough with 1000-qubit chip.', links=[], newsletter='The Deep View', date='2026-04-07'),
]
clusters = embed_and_cluster(records)
print(f'Stories: {len(records)}, Clusters after embedding (threshold=0.55): {len(clusters)}')
for i, cluster in enumerate(clusters):
    print(f'  Cluster {i}: {[r.newsletter + \": \" + r.body[:40] for r in cluster]}')
print()
print('Expected: OpenAI pair in same cluster, others separate or partially grouped')
"
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `config.py` has no `dedup_candidate_min` field and `dedup_threshold` default is 0.55
- [ ] `.env` has `DEDUP_THRESHOLD=0.55` and no `DEDUP_CANDIDATE_MIN` line
- [ ] `.env.example` comment block reflects single-threshold design
- [ ] `processing/embedder.py` has no `find_candidate_cluster_pairs` function
- [ ] `ai/claude_client.py` has `filter_noise`, `refine_clusters`, and retains `filter_stories`; `confirm_dedup_candidates` and `_DEDUP_TOOL_SCHEMA` are absent
- [ ] `processing/digest_builder.py` imports `filter_noise`, `refine_clusters`; does not import `confirm_dedup_candidates` or `find_candidate_cluster_pairs`; pipeline has 7 stages
- [ ] Full test suite passes with no regressions

---

## ROLLBACK CONSIDERATIONS

All changes are in Python source files (no DB migrations, no data changes). Rollback = `git revert` or `git checkout` on the modified files.

After rollback, `.env` must manually be updated back to `DEDUP_THRESHOLD=0.65` and `DEDUP_CANDIDATE_MIN=0.45` since `.env` is gitignored.

---

## ACCEPTANCE CRITERIA

- [ ] `filter_noise` is a new async function in `claude_client.py` with its own tool schema, maximally conservative bias, and fail-open behavior
- [ ] `refine_clusters` is a new async function in `claude_client.py` with three-way `same_story | related_but_distinct | different` classification and internal union-find
- [ ] `confirm_dedup_candidates`, `_DEDUP_TOOL_SCHEMA`, and all old dedup constants are removed
- [ ] `find_candidate_cluster_pairs` is removed from `embedder.py`
- [ ] `config.py` has single `dedup_threshold = 0.55`, no `dedup_candidate_min`
- [ ] `digest_builder.py` pipeline is 7 stages: parse → noise_filter → embed → refine → dedup → editorial
- [ ] All 22 tests in `test_claude_client.py` pass
- [ ] All 6 tests in `test_embedder.py` pass
- [ ] Full suite passes with no regressions
- [ ] Manual spot-check shows OpenAI pair correctly clustered together at threshold=0.55

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed immediately
- [ ] All validation commands executed successfully
- [ ] Full test suite passes
- [ ] No linting or type checking errors
- [ ] Manual spot-check confirms correct clustering behavior
- [ ] Acceptance criteria all met

---

## NOTES

**Why `merge_confirmed_clusters` is retained**: It stays in `deduplicator.py` and its tests remain in `test_deduplicator.py`. It is not called in the main pipeline after this change, but removing it would require deleting 5 tests and it may be useful for future pipeline variations. Leave it in place.

**Fail-open semantics clarification**:
- `filter_noise` on failure → return all stories (don't remove anything)
- `refine_clusters` on failure for a cluster's pairs → keep that cluster intact (trust embedding result rather than splitting to singletons)

**Union-find scope in `refine_clusters`**: The union-find is applied *per cluster*, not globally. Each cluster's stories start as their own components; only `same_story` pairs within that cluster trigger a union. This correctly handles transitivity within a cluster (A+B same, B+C same → A+B+C merged) without cross-cluster interference.

**`_build_refine_message` input type**: The function takes `list[tuple[StoryRecord, StoryRecord]]`. The caller (`refine_clusters`) builds this list internally from cluster pairs before batching.

**Threshold 0.55 rationale**: Modestly lower than 0.65 to increase recall for cross-newsletter same-story candidates. Not aggressively low (0.3–0.4) to avoid sweeping unrelated stories into the same cluster. The LLM pairwise refinement handles the increased noise in larger clusters.

**Stage numbering**: The pipeline goes from 6 to 7 stages. All stage log messages should use `/7` not `/6`.

**`defaultdict` import in `refine_clusters`**: Import `defaultdict` from `collections` at the module level in `claude_client.py` (add to existing imports), do not use a local import inside the function.

---

## VALIDATION OUTPUT REFERENCE

Every item the user must visually verify after running `/execute`. Each item appears exactly once.

---

- Item to check:
  `python -c "from config import settings; assert settings.dedup_threshold == 0.55; assert not hasattr(settings, 'dedup_candidate_min'); print('OK')"`
  Expected output or result:
  ```
  OK
  ```

- Item to check:
  `python -c "from processing.embedder import embed_and_cluster; from processing import embedder; assert not hasattr(embedder, 'find_candidate_cluster_pairs'); print('OK')"`
  Expected output or result:
  ```
  OK
  ```

- Item to check:
  ```
  python -c "
  from ai.claude_client import (
      _NOISE_TOOL_NAME, _NOISE_TOOL_SCHEMA, _NOISE_BATCH_SIZE,
      _REFINE_TOOL_NAME, _REFINE_TOOL_SCHEMA, _REFINE_BATCH_SIZE,
      filter_noise, refine_clusters, filter_stories,
  )
  from ai import claude_client
  assert not hasattr(claude_client, 'confirm_dedup_candidates'), 'confirm_dedup_candidates not removed'
  assert not hasattr(claude_client, '_DEDUP_TOOL_SCHEMA'), '_DEDUP_TOOL_SCHEMA not removed'
  print('claude_client imports OK')
  "
  ```
  Expected output or result:
  ```
  claude_client imports OK
  ```

- Item to check:
  ```
  python -c "
  import inspect
  from processing import digest_builder
  src = inspect.getsource(digest_builder)
  assert 'filter_noise' in src
  assert 'refine_clusters' in src
  assert 'Stage 3/7' in src
  assert 'Stage 7/7' in src
  assert 'confirm_dedup_candidates' not in src
  assert 'find_candidate_cluster_pairs' not in src
  assert 'merge_confirmed_clusters' not in src
  print('digest_builder OK')
  "
  ```
  Expected output or result:
  ```
  digest_builder OK
  ```

- Item to check:
  ```
  python -c "
  from config import settings
  from processing.embedder import embed_and_cluster
  from processing.deduplicator import deduplicate, merge_confirmed_clusters, select_representative
  from ai.claude_client import filter_noise, filter_stories, refine_clusters
  from processing.digest_builder import build_digest
  from ai import claude_client
  from processing import embedder
  assert not hasattr(claude_client, 'confirm_dedup_candidates'), 'confirm_dedup_candidates not removed'
  assert not hasattr(claude_client, '_DEDUP_TOOL_SCHEMA'), '_DEDUP_TOOL_SCHEMA not removed'
  assert not hasattr(embedder, 'find_candidate_cluster_pairs'), 'find_candidate_cluster_pairs not removed'
  assert not hasattr(settings, 'dedup_candidate_min'), 'dedup_candidate_min not removed from config'
  assert settings.dedup_threshold == 0.55, f'Expected 0.55, got {settings.dedup_threshold}'
  print('All imports and config OK')
  "
  ```
  Expected output or result:
  ```
  All imports and config OK
  ```

- Item to check:
  `python -m pytest tests/test_embedder.py -v`
  Expected output or result:
  ```
  tests/test_embedder.py::test_embed_and_cluster_empty_input PASSED
  tests/test_embedder.py::test_embed_and_cluster_single_item PASSED
  tests/test_embedder.py::test_embed_and_cluster_identical_stories_same_cluster PASSED
  tests/test_embedder.py::test_embed_and_cluster_unrelated_stories_separate_clusters PASSED
  tests/test_embedder.py::test_embed_and_cluster_all_records_present PASSED
  tests/test_embedder.py::test_embed_and_cluster_no_record_in_multiple_clusters PASSED

  ============================== 6 passed
  ```

- Item to check:
  `python -m pytest tests/test_claude_client.py -v`
  Expected output or result:
  ```
  tests/test_claude_client.py::test_filter_batch_size PASSED
  tests/test_claude_client.py::test_filter_tool_name PASSED
  tests/test_claude_client.py::test_filter_schema_decisions_array PASSED
  tests/test_claude_client.py::test_filter_batch_split_75_stories PASSED
  tests/test_claude_client.py::test_filter_batch_split_26_stories PASSED
  tests/test_claude_client.py::test_filter_message_includes_newsletter_name PASSED
  tests/test_claude_client.py::test_filter_message_includes_title_when_present PASSED
  tests/test_claude_client.py::test_filter_message_includes_body_excerpt PASSED
  tests/test_claude_client.py::test_filter_message_truncates_long_body PASSED
  tests/test_claude_client.py::test_noise_batch_size PASSED
  tests/test_claude_client.py::test_noise_tool_name PASSED
  tests/test_claude_client.py::test_noise_schema_is_noise_field PASSED
  tests/test_claude_client.py::test_noise_batch_split_95_stories PASSED
  tests/test_claude_client.py::test_noise_message_includes_newsletter_name PASSED
  tests/test_claude_client.py::test_noise_message_includes_body_excerpt PASSED
  tests/test_claude_client.py::test_noise_message_truncates_long_body PASSED
  tests/test_claude_client.py::test_refine_batch_size PASSED
  tests/test_claude_client.py::test_refine_tool_name PASSED
  tests/test_claude_client.py::test_refine_schema_relationship_enum PASSED
  tests/test_claude_client.py::test_refine_relationship_enum_values PASSED
  tests/test_claude_client.py::test_refine_message_labels_newsletter PASSED
  tests/test_claude_client.py::test_refine_batch_split_45_pairs PASSED

  ============================== 22 passed
  ```

- Item to check:
  `python -m pytest tests/test_deduplicator.py -v`
  Expected output or result:
  ```
  27 passed
  ```
  (All 27 existing tests pass unchanged.)

- Item to check:
  `python -m pytest tests/ -v`
  Expected output or result:
  Full suite passes. Summary line shows no failures. Expected total: 114 passed (107 prior + 7 net new: +13 noise/refine tests, −6 removed dedup tests).

- Item to check:
  Level 4 manual spot-check — `embed_and_cluster` with 5 records at threshold=0.55
  Expected output or result:
  ```
  Stories: 5, Clusters after embedding (threshold=0.55): 4 (or fewer)
    Cluster 0: ['TLDR AI: OpenAI released GPT-5 today with major...', 'The Deep View: OpenAI unveils GPT-5 featuring enha...']
    Cluster 1: ['TLDR: Nvidia announced new GTC datacenter chips...']
    Cluster 2: ['TLDR AI: Nvidia shifts strategy to inference cost...']
    Cluster 3: ['The Deep View: Google announces quantum computing...']

  Expected: OpenAI pair in same cluster, others separate or partially grouped
  ```
  (Exact cluster count may vary ±1 depending on Nvidia pair similarity at 0.55. The key signal is the two OpenAI stories appearing together.)

- Item to check:
  `config.py` has no `dedup_candidate_min` field and `dedup_threshold` default is 0.55
  Expected output or result:
  File `config.py` contains `dedup_threshold: float = 0.55` and does not contain the string `dedup_candidate_min`.

- Item to check:
  `.env` has `DEDUP_THRESHOLD=0.55` and no `DEDUP_CANDIDATE_MIN` line
  Expected output or result:
  File `.env` contains `DEDUP_THRESHOLD=0.55` and does not contain `DEDUP_CANDIDATE_MIN`.

- Item to check:
  `.env.example` comment block reflects single-threshold design
  Expected output or result:
  File `.env.example` contains `DEDUP_THRESHOLD=0.55`, does not contain `DEDUP_CANDIDATE_MIN`, and the comment above `DEDUP_THRESHOLD` describes single-threshold candidate grouping (no mention of two-band approach).

- Item to check:
  `processing/embedder.py` has no `find_candidate_cluster_pairs` function
  Expected output or result:
  File `processing/embedder.py` does not contain the string `find_candidate_cluster_pairs`.

- Item to check:
  `ai/claude_client.py` has `filter_noise`, `refine_clusters`, retains `filter_stories`; `confirm_dedup_candidates` and `_DEDUP_TOOL_SCHEMA` are absent
  Expected output or result:
  File `ai/claude_client.py` contains `def filter_noise`, `async def refine_clusters`, `async def filter_stories`, and does not contain `confirm_dedup_candidates` or `_DEDUP_TOOL_SCHEMA`.

- Item to check:
  `processing/digest_builder.py` imports `filter_noise`, `refine_clusters`; does not import `confirm_dedup_candidates` or `find_candidate_cluster_pairs`; pipeline has 7 stages
  Expected output or result:
  File `processing/digest_builder.py` contains `filter_noise` and `refine_clusters` in its imports; does not contain `confirm_dedup_candidates` or `find_candidate_cluster_pairs`; contains `Stage 7/7`.
