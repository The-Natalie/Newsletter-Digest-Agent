# Feature: processing/embedder.py

The following plan should be complete, but validate codebase patterns before starting.

Pay special attention to: `community_detection` signature (min_community_size=1 is required, not the default 10), lazy model loading, the `StoryChunk` dataclass shape (consumed by deduplicator.py next), and the `processing/__init__.py` package marker.

## Feature Description

Create `processing/embedder.py` — the module that takes a `list[ParsedEmail]`, segments each email body into story candidates, encodes them with `sentence-transformers` (`all-MiniLM-L6-v2`), and clusters them using `community_detection` at the configured cosine similarity threshold. Returns `list[list[StoryChunk]]` — each inner list is one cluster of semantically similar stories.

## User Story

As the digest pipeline,
I want a function that accepts parsed emails and returns story clusters grouped by semantic similarity,
So that the deduplicator can merge overlapping stories and the AI client can generate one digest entry per unique topic.

## Problem Statement

Without semantic clustering, the pipeline has no way to detect when multiple newsletters cover the same story. Every email would produce independent digest entries, resulting in duplicate content.

## Scope

- In scope: `processing/__init__.py`, `StoryChunk` dataclass, story segmentation, sentence-transformer encoding, community_detection clustering, lazy model caching, `embed_and_cluster()` function
- Out of scope: merging story groups into digest entries (done in `deduplicator.py`), persisting embeddings across runs (Phase 2)

## Solution Statement

Segment each `ParsedEmail.body` at double-newline and markdown horizontal-rule boundaries, filter segments under 50 chars, encode the first 400 chars of each segment with `SentenceTransformer("all-MiniLM-L6-v2")`, and run `st_util.community_detection(embeddings, threshold=settings.dedup_threshold, min_community_size=1)`. Return all clusters (including singletons) as `list[list[StoryChunk]]`. Lazy-load and cache the model at module level to avoid reloading on repeated calls.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Low-Medium
**Primary Systems Affected**: `processing/embedder.py`, `processing/__init__.py`
**Dependencies**: `sentence-transformers==5.3.0` (installed), `torch` (installed), `config.settings`
**Assumptions**: `ParsedEmail` is imported from `ingestion.email_parser`; `settings.dedup_threshold` is 0.82 by default

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 1–36) — establishes module-level logger, `@dataclass` + `field(default_factory=list)` pattern, `from __future__ import annotations`, private helpers with `_` prefix
- `ingestion/email_parser.py` (lines 30–36) — `ParsedEmail` shape: `subject`, `sender`, `date`, `body`, `links` — embedder receives this as input
- `config.py` (whole file) — `settings.dedup_threshold: float = 0.82` is the threshold to pass to `community_detection`
- `PRD.md` §7 Feature 3 (lines 274–288) — full spec: segmentation heuristics, `all-MiniLM-L6-v2`, `community_detection` at 0.82, each cluster → one digest entry

### New Files to Create

- `processing/__init__.py` — empty package marker
- `processing/embedder.py` — `StoryChunk`, `_get_model()`, `_segment_email()`, `_encoding_text()`, `embed_and_cluster()`

### Relevant Documentation — READ BEFORE IMPLEMENTING

- sentence-transformers community_detection: https://www.sbert.net/docs/package_reference/util.html#sentence_transformers.util.community_detection
  - Why: exact signature — `(embeddings, threshold=0.75, min_community_size=10, batch_size=1024, show_progress_bar=False) -> list[list[int]]` — default min_community_size is 10; **MUST override to 1**
- SentenceTransformer.encode: https://www.sbert.net/docs/package_reference/SentenceTransformer.html#sentence_transformers.SentenceTransformer.encode
  - Why: `convert_to_tensor=True` returns a `torch.Tensor` (required by community_detection); `show_progress_bar=False` suppresses output

### Patterns to Follow

**Module structure** (mirror `ingestion/email_parser.py`):
```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sentence_transformers import SentenceTransformer
from sentence_transformers import util as st_util

from config import settings
from ingestion.email_parser import ParsedEmail

logger = logging.getLogger(__name__)
```

**Lazy model caching** (module-level singleton):
```python
_model: SentenceTransformer | None = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model
```

**Module-level constants** (not env vars — tuning values internal to this module):
```python
_MODEL_NAME = "all-MiniLM-L6-v2"
_MIN_CHUNK_CHARS = 50
_MAX_ENCODING_CHARS = 400
```

---

## IMPLEMENTATION PLAN

### Phase 1: Package scaffolding + data model

Create `processing/__init__.py` and define `StoryChunk`.

### Phase 2: Segmentation and encoding helpers

Implement `_segment_email()` (body → story chunks), `_encoding_text()` (chunk → encoding string), and `_get_model()` (lazy model loader).

### Phase 3: Top-level cluster function

Implement `embed_and_cluster()` that orchestrates segmentation, encoding, and clustering.

---

## STEP-BY-STEP TASKS

### TASK 1 — CREATE `processing/__init__.py`

- **IMPLEMENT**: Empty file; marks `processing/` as a Python package
- **VALIDATE**: `python -c "import processing; print('processing package OK')"`

---

### TASK 2 — CREATE `processing/embedder.py` — imports, constants, `StoryChunk`

- **IMPLEMENT**: All imports, module-level logger, constants, model cache, `StoryChunk` dataclass
- **IMPORTS**:
  ```python
  from __future__ import annotations

  import logging
  import re
  from dataclasses import dataclass, field

  from sentence_transformers import SentenceTransformer
  from sentence_transformers import util as st_util

  from config import settings
  from ingestion.email_parser import ParsedEmail
  ```
- **CONSTANTS**:
  ```python
  _MODEL_NAME = "all-MiniLM-L6-v2"
  _MIN_CHUNK_CHARS = 50      # segments shorter than this are filtered out
  _MAX_ENCODING_CHARS = 400  # max chars fed to the encoder per chunk
  ```
- **MODEL CACHE**:
  ```python
  _model: SentenceTransformer | None = None
  ```
- **`StoryChunk` dataclass**:
  ```python
  @dataclass
  class StoryChunk:
      text: str                # full story text (for the AI prompt in digest_builder)
      sender: str              # newsletter display name (for source attribution)
      links: list[dict] = field(default_factory=list)  # links from the source email
  ```
- **GOTCHA**: `StoryChunk` must carry `links` from the source `ParsedEmail` because the deduplicator needs all links per story for source attribution in the final digest. Do NOT strip links at this stage.
- **VALIDATE**: `python -c "from processing.embedder import StoryChunk; print(list(StoryChunk.__dataclass_fields__.keys()))"`
  Expected: `['text', 'sender', 'links']`

---

### TASK 3 — ADD `_get_model()`, `_segment_email()`, `_encoding_text()`

**`_get_model()`**:
- **IMPLEMENT**: Lazy-load `SentenceTransformer(_MODEL_NAME)`, cache in `_model` global, log on first load
- **GOTCHA**: The model weights (~22MB) download automatically on first use from Hugging Face. Subsequent calls use the local cache (~/.cache/torch/sentence_transformers/). Do not attempt to pre-download or manage the cache manually.
- **GOTCHA**: Model loading takes 1–3 seconds on first call per process. This is expected; the lazy pattern means import time stays fast.

```python
def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model
```

**`_segment_email(email: ParsedEmail) -> list[StoryChunk]`**:
- **IMPLEMENT**: Split `email.body` at double newlines or markdown horizontal rules; filter short segments
- **SPLIT PATTERN**: `r'\n{2,}|(?m)^\s*[-*_]{3,}\s*$'`
  - `\n{2,}` — two or more consecutive newlines (blank line boundary)
  - `(?m)^\s*[-*_]{3,}\s*$` — a line consisting entirely of dashes, asterisks, or underscores (markdown `---`, `***`, `___`)
- **FILTER**: Keep only segments with `len(seg.strip()) >= _MIN_CHUNK_CHARS`
- **EACH CHUNK**: `StoryChunk(text=seg.strip(), sender=email.sender, links=email.links)`
- **GOTCHA**: All chunks from the same email share the same `links` list (the email's links, not story-specific links). The deduplicator merges links per cluster. Story-level link attribution is a Phase 2 enhancement.
- **LOG**: Log a debug line per email: `logger.debug("Email from %s segmented into %d chunks", email.sender, len(chunks))`
- **RETURN**: `list[StoryChunk]` (may be empty if body has no segments long enough)

```python
_SPLIT_PATTERN = re.compile(r'\n{2,}|(?m)^\s*[-*_]{3,}\s*$')

def _segment_email(parsed_email: ParsedEmail) -> list[StoryChunk]:
    """Split email body into story candidates at blank-line and horizontal-rule boundaries."""
    segments = _SPLIT_PATTERN.split(parsed_email.body)
    chunks = []
    for seg in segments:
        seg = seg.strip()
        if len(seg) >= _MIN_CHUNK_CHARS:
            chunks.append(StoryChunk(
                text=seg,
                sender=parsed_email.sender,
                links=parsed_email.links,
            ))
    logger.debug("Email from %s segmented into %d chunks", parsed_email.sender, len(chunks))
    return chunks
```

**`_encoding_text(chunk: StoryChunk) -> str`**:
- **IMPLEMENT**: Return the first `_MAX_ENCODING_CHARS` characters of `chunk.text`
- **RATIONALE**: The PRD says "encode story titles + first 2–3 sentences". A 400-char truncation approximates this for typical newsletter story blocks without sentence-boundary parsing.

```python
def _encoding_text(chunk: StoryChunk) -> str:
    """Return the text used for semantic encoding (title + first ~2–3 sentences)."""
    return chunk.text[:_MAX_ENCODING_CHARS]
```

---

### TASK 4 — IMPLEMENT `embed_and_cluster()`

- **SIGNATURE**: `def embed_and_cluster(parsed_emails: list[ParsedEmail]) -> list[list[StoryChunk]]:`
- **IMPLEMENT**: Full pipeline — segment → encode → cluster → return

**Step-by-step logic:**

1. Guard: `if not parsed_emails: return []`
2. Segment all emails: build `all_chunks: list[StoryChunk]` by extending from `_segment_email()` per email
3. Guard: `if not all_chunks: return []`
4. Short-circuit: `if len(all_chunks) == 1: return [[all_chunks[0]]]`
5. Encode: `embeddings = _get_model().encode([_encoding_text(c) for c in all_chunks], convert_to_tensor=True, show_progress_bar=False)`
6. Cluster:
   ```python
   clusters_indices = st_util.community_detection(
       embeddings,
       threshold=settings.dedup_threshold,
       min_community_size=1,
       show_progress_bar=False,
   )
   ```
7. Build result: `return [[all_chunks[i] for i in cluster] for cluster in clusters_indices]`
8. Log: `logger.info("Clustered %d chunks into %d groups (threshold=%.2f)", len(all_chunks), len(result), settings.dedup_threshold)`

- **GOTCHA**: `min_community_size=1` is **mandatory** — the default is 10, which would discard all small clusters (typical for 2–10 emails). **Verified behavior**: `community_detection` with `min_community_size=1` returns every index exactly once, including isolated singletons as single-element clusters. This guarantees no stories are lost.
- **GOTCHA**: `convert_to_tensor=True` must be passed to `encode()` — `community_detection` requires a `torch.Tensor`, not a numpy array or list.
- **GOTCHA**: Do NOT pass `settings.dedup_threshold` as a default parameter value in the function signature (`def f(threshold=settings.dedup_threshold)`) — this evaluates at import time. Read `settings.dedup_threshold` inside the function body.
- **VALIDATE**: Full smoke test (see Testing Strategy)

**Full function:**
```python
def embed_and_cluster(parsed_emails: list[ParsedEmail]) -> list[list[StoryChunk]]:
    """Segment emails into story chunks, encode, and cluster by semantic similarity.

    Args:
        parsed_emails: List of parsed email objects from parse_emails().

    Returns:
        List of story clusters. Each cluster is a list of StoryChunks representing
        semantically similar stories across newsletters. Singletons (unique stories)
        are returned as single-element clusters. Every story chunk is in exactly
        one cluster.
    """
    if not parsed_emails:
        return []

    all_chunks: list[StoryChunk] = []
    for parsed_email in parsed_emails:
        all_chunks.extend(_segment_email(parsed_email))

    if not all_chunks:
        return []

    if len(all_chunks) == 1:
        return [[all_chunks[0]]]

    model = _get_model()
    encoding_texts = [_encoding_text(c) for c in all_chunks]
    embeddings = model.encode(encoding_texts, convert_to_tensor=True, show_progress_bar=False)

    clusters_indices = st_util.community_detection(
        embeddings,
        threshold=settings.dedup_threshold,
        min_community_size=1,
        show_progress_bar=False,
    )

    result = [[all_chunks[i] for i in cluster] for cluster in clusters_indices]

    logger.info(
        "Clustered %d story chunks into %d groups (threshold=%.2f)",
        len(all_chunks),
        len(result),
        settings.dedup_threshold,
    )
    return result
```

---

## TESTING STRATEGY

No separate test file required. Validation uses synthetic `ParsedEmail` objects to confirm clustering behavior end-to-end.

### Smoke Test — Two similar stories cluster together

```python
from ingestion.email_parser import ParsedEmail
from processing.embedder import embed_and_cluster

email1 = ParsedEmail(
    subject="AI Newsletter",
    sender="TLDR AI",
    date=None,
    body="OpenAI launches GPT-5 with multimodal capabilities. This new model outperforms all benchmarks. It is available via API starting today.",
    links=[],
)
email2 = ParsedEmail(
    subject="The Rundown",
    sender="The Rundown",
    date=None,
    body="OpenAI releases GPT-5 today. The model supports images, audio, and text. Developers can access it through the OpenAI API immediately.",
    links=[],
)
email3 = ParsedEmail(
    subject="Startup News",
    sender="Startup Weekly",
    date=None,
    body="A new climate tech startup raised $50 million in Series B funding. The company builds direct air capture technology for removing CO2 from the atmosphere.",
    links=[],
)

clusters = embed_and_cluster([email1, email2, email3])
# email1 and email2 are about the same story (GPT-5); email3 is unrelated
# Expected: 2 clusters — one with 2 chunks (GPT-5 stories), one singleton (climate)
print(f"Number of clusters: {len(clusters)}")
for i, cluster in enumerate(clusters):
    print(f"  Cluster {i}: {[c.sender for c in cluster]}")
```

### Edge Cases

- `embed_and_cluster([])` → `[]`
- Single email with one segment → `[[StoryChunk(...)]]` (one cluster of one)
- All stories unrelated → N clusters of size 1
- All stories identical → 1 cluster of size N

---

## VALIDATION COMMANDS

### Level 1: Package import

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import processing; print('processing package OK')"
```
Expected output: `processing package OK`

### Level 2: Module import and StoryChunk fields

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.embedder import embed_and_cluster, StoryChunk; print('import OK'); print(list(StoryChunk.__dataclass_fields__.keys()))"
```
Expected output:
```
import OK
['text', 'sender', 'links']
```

### Level 3: Empty input guard

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import embed_and_cluster
result = embed_and_cluster([])
print('empty input result:', result)
"
```
Expected output: `empty input result: []`

### Level 4: Clustering smoke test

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import ParsedEmail
from processing.embedder import embed_and_cluster

email1 = ParsedEmail(subject='AI News', sender='TLDR AI', date=None,
    body='OpenAI launches GPT-5 with multimodal capabilities. This new model outperforms all benchmarks. It is available via API starting today.',
    links=[])
email2 = ParsedEmail(subject='Rundown', sender='The Rundown', date=None,
    body='OpenAI releases GPT-5 today. The model supports images, audio, and text. Developers can access it through the OpenAI API immediately.',
    links=[])
email3 = ParsedEmail(subject='Startup', sender='Startup Weekly', date=None,
    body='A new climate tech startup raised 50 million in Series B funding. The company builds direct air capture technology for removing CO2 from the atmosphere.',
    links=[])

clusters = embed_and_cluster([email1, email2, email3])
print(f'Number of clusters: {len(clusters)}')
for i, cluster in enumerate(clusters):
    senders = [c.sender for c in cluster]
    print(f'  Cluster {i}: {senders}')

# Verify every chunk is in exactly one cluster
total_chunks = sum(len(c) for c in clusters)
print(f'Total chunks across all clusters: {total_chunks}')
assert total_chunks == 3, f'Expected 3 total chunks, got {total_chunks}'
print('Coverage assertion PASSED')
"
```
Expected output:
```
Number of clusters: 2
  Cluster 0: ['TLDR AI', 'The Rundown']
  Cluster 1: ['Startup Weekly']
Total chunks across all clusters: 3
Coverage assertion PASSED
```
*(Cluster ordering may differ; the key assertions are: 2 clusters total, 3 total chunks, the two GPT-5 stories in one cluster.)*

### Level 5: All-singleton case + single-email guard

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import ParsedEmail
from processing.embedder import embed_and_cluster

# Single email
single = [ParsedEmail(subject='X', sender='A', date=None,
    body='A completely unique story about something specific that no other newsletter covers.',
    links=[])]
result = embed_and_cluster(single)
print('Single email clusters:', len(result))
assert len(result) == 1 and len(result[0]) == 1
print('Single email assertion PASSED')

# Three unrelated stories
email1 = ParsedEmail(subject='X', sender='A', date=None, body='The French government announced new taxes on luxury goods effective January. This will affect fashion brands headquartered in Paris significantly.', links=[])
email2 = ParsedEmail(subject='Y', sender='B', date=None, body='NASA successfully launched its new Artemis mission to the Moon. The crew includes the first woman astronaut to orbit the Moon.', links=[])
email3 = ParsedEmail(subject='Z', sender='C', date=None, body='Python 4.0 was released with structural pattern matching improvements. The new release drops support for Python 2 compatible syntax entirely.', links=[])
clusters = embed_and_cluster([email1, email2, email3])
print('All-singleton cluster count:', len(clusters))
total = sum(len(c) for c in clusters)
assert total == 3, f'Expected 3, got {total}'
print('All-singleton assertion PASSED')
"
```
Expected output:
```
Single email clusters: 1
Single email assertion PASSED
All-singleton cluster count: 3
All-singleton assertion PASSED
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `processing/__init__.py` exists (empty file)
- [ ] `processing/embedder.py` imports cleanly
- [ ] `StoryChunk` has exactly 3 fields: `text`, `sender`, `links`
- [ ] `embed_and_cluster([])` returns `[]`
- [ ] Clustering smoke test: two GPT-5 stories cluster together, climate story is separate
- [ ] Total chunks across all clusters equals total input segments (no stories lost)
- [ ] `min_community_size=1` is passed to `community_detection` (not the default 10)
- [ ] `convert_to_tensor=True` is passed to `model.encode()`
- [ ] `settings.dedup_threshold` is read inside the function body (not as a default argument)

## ROLLBACK CONSIDERATIONS

- New files only; rollback = delete `processing/__init__.py` and `processing/embedder.py`
- No database changes, migrations, or config changes required
- Model download cached at `~/.cache/torch/sentence_transformers/` — unrelated to the project

## ACCEPTANCE CRITERIA

- [ ] `processing/__init__.py` exists
- [ ] `embed_and_cluster()` accepts `list[ParsedEmail]`, returns `list[list[StoryChunk]]`
- [ ] `StoryChunk` has fields: `text`, `sender`, `links`
- [ ] Empty input → `[]`
- [ ] Single segment → one cluster of one
- [ ] Two semantically similar stories from different emails → same cluster
- [ ] Semantically unrelated stories → separate clusters
- [ ] Every input chunk appears in exactly one output cluster
- [ ] `min_community_size=1` used (no stories dropped)
- [ ] `convert_to_tensor=True` used with encode
- [ ] `settings.dedup_threshold` used for threshold value
- [ ] All 5 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1: `processing/__init__.py` created and validated
- [ ] Task 2–4: `processing/embedder.py` created and validated
- [ ] Level 1 validation passed
- [ ] Level 2 validation passed
- [ ] Level 3 validation passed
- [ ] Level 4 validation passed
- [ ] Level 5 validation passed

---

## NOTES

**Why `min_community_size=1` is mandatory:**
The `community_detection` default is `min_community_size=10`, which would silently discard every community smaller than 10. In a typical run of 2–10 newsletter emails, almost all communities have 1–3 members. Using the default would drop all stories. `min_community_size=1` is **verified** (tested above) to return every index exactly once, including singletons.

**Why lazy model loading:**
`SentenceTransformer("all-MiniLM-L6-v2")` takes 1–3 seconds and triggers a model download on first use. Instantiating it at import time would slow down all imports of this module. The lazy pattern delays loading until the first actual encode call, keeping the import chain fast.

**Why 400-char truncation for encoding text:**
The `all-MiniLM-L6-v2` model was trained with a 256-token limit (roughly 200 words / ~1,000 chars for typical English). A 400-char prefix reliably captures the title and first 2–3 sentences of a newsletter story block without truncating mid-sentence on most inputs. Sending the full story text would be fine too — but truncation is faster and the first sentences carry the most semantic signal for similarity.

**Why `links` are copied per-email rather than per-segment:**
Story-level link attribution (which specific link goes with which story segment) would require parsing the HTML at the story level — complex and out of scope for MVP. Per-email links are sufficient for the deduplicator to attach source links to digest entries. Phase 2 can refine this.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `.venv/bin/python -c "import processing; print('processing package OK')"`
  Expected output or result:
  `processing package OK`

- Item to check:
  `.venv/bin/python -c "from processing.embedder import embed_and_cluster, StoryChunk; print('import OK'); print(list(StoryChunk.__dataclass_fields__.keys()))"`
  Expected output or result:
  ```
  import OK
  ['text', 'sender', 'links']
  ```

- Item to check:
  `.venv/bin/python -c "from processing.embedder import embed_and_cluster; result = embed_and_cluster([]); print('empty input result:', result)"`
  Expected output or result:
  `empty input result: []`

- Item to check:
  Clustering smoke test — `embed_and_cluster([email1, email2, email3])` with two GPT-5 stories and one climate story
  Expected output or result:
  ```
  Number of clusters: 2
    Cluster 0: ['TLDR AI', 'The Rundown']
    Cluster 1: ['Startup Weekly']
  Total chunks across all clusters: 3
  Coverage assertion PASSED
  ```
  *(Cluster ordering may differ; two clusters total, all three chunks covered, GPT-5 stories together)*

- Item to check:
  Single-email guard + all-singleton test
  Expected output or result:
  ```
  Single email clusters: 1
  Single email assertion PASSED
  All-singleton cluster count: 3
  All-singleton assertion PASSED
  ```
