# Feature: Loop 9D — Eliminate `<UNKNOWN>` Outputs and Reduce Incorrect Source Links

The following plan should be complete, but validate all file paths, import names, and code
patterns before implementing.

## Feature Description

Two distinct failure classes remain after Loop 9C:

1. **`<UNKNOWN>` generation outputs**: Short roundup items produced by `_split_list_section()`
   become story groups with 30–80 chars of chunk text. Claude cannot satisfy the existing
   "2–4 sentences" summary contract without inventing details, so it returns `<UNKNOWN>` or
   empty fields as a compliant refusal. These stories are legitimate and must not be dropped.

2. **Incorrect source links**: Four specific anchor failures are observed in the latest Deep
   View run. One is a confirmed CTA filter gap ("Watch now"). Three others have unknown root
   causes: the wrong anchor may be winning due to a scoring issue, or a wrong chunk may be
   in the cluster due to a clustering false positive. **No scoring changes are made until the
   diagnostic script confirms the root cause for each remaining case.**

## Specific Failures Being Fixed (This Loop)

| Story (as generated) | Wrong anchor | Root cause | Disposition |
|---|---|---|---|
| "Mistral releases Leanstral..." | (empty / `<UNKNOWN>`) | Sparse input: 65-char chunk; Claude cannot satisfy "2–4 sentences" | **Fix in this loop** |
| "Mistral releases Leanstral..." | "Watch now" | CTA miss: "watch now" not in `_CTA_ANCHOR_SIGNALS` | **Fix in this loop** |
| "Anthropic also courts private equity..." | "small robots that looked like they came straight out of WALL-E" | Unconfirmed: anchor-length scoring OR clustering false positive | **Diagnose only** |
| "Sam Altman tells students AGI..." | "Google" | Unconfirmed: may be clustering false positive OR scoring | **Diagnose only** |
| "Meta commits $27B to Nebius..." | "manage all of these features from one central hub" | Unconfirmed: may be clustering false positive OR scoring | **Diagnose only** |

## Scope

- **In scope**: sparse-input generation fix; confirmed CTA filter gaps; diagnostic script
  that identifies the exact root cause (scoring vs. clustering) for each remaining source-link
  failure; optional scoring change applied only if diagnostic confirms a scoring root cause.
- **Out of scope**: any scoring change that is not tied to a specific confirmed failure;
  clustering threshold tuning; `embedder.py` changes; multi-paragraph section merging.

## Solution Statement

Two confirmed fixes (sparse input, CTA gap), one diagnostic script, and one conditional
scoring fix that is only applied if the diagnostic output confirms it is warranted:

1. **CTA filter gap** (`deduplicator.py`): Add "watch now" and a small set of confirmed-missing
   CTA patterns to `_CTA_ANCHOR_SIGNALS`. Root cause is confirmed: anchor text matches the
   known CTA pattern family; the word "watch now" is absent from the current tuple.

2. **Sparse input generation fallback** (`claude_client.py`): Add `_SPARSE_CHUNK_THRESHOLD`
   constant. Annotate sparse story groups in `_build_user_message()` with explicit permission
   to produce one-sentence entries. Relax the summary schema from "2–4" to "1–4 sentences".

3. **`scripts/inspect_clusters.py`** (new): Diagnostic script that runs the pipeline through
   deduplication on a real `.eml` file and prints, for each story group, every chunk's
   candidate links, the CTA filter result, the `_score_source()` value, and the winner.
   This script determines whether each of the three unconfirmed failures above is caused by
   the scoring function or by a wrong chunk entering the cluster.

4. **Conditional: `_score_source()` word-count cap** (only if diagnostic confirms): If the
   diagnostic shows that "WALL-E", "Google", or "manage all features" anchors are winning
   because the correct chunk IS in the cluster but the scoring function prefers a long prose
   anchor, then add `_ANCHOR_IDEAL_MAX_WORDS = 7` and replace `len(anchor)` with
   `word_count if word_count <= _ANCHOR_IDEAL_MAX_WORDS else 0`. If the diagnostic instead
   shows that the wrong chunk is in the cluster, the scoring change does not apply and the
   failure is deferred to a clustering investigation.

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low (confirmed fixes) + diagnostic
**Primary Systems Affected**: `ai/claude_client.py`, `processing/deduplicator.py`
**Dependencies**: None new
**Assumptions**:
- `_split_list_section()` is working and producing 30–80 char chunks for roundup items
- "Watch now" failure is from §15 Slack sponsor in Deep View; anchor appears verbatim
- The three unconfirmed source-link failures require the diagnostic script to resolve

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `processing/deduplicator.py` (lines 11–36) — `_CTA_ANCHOR_SIGNALS`; new entries go here.
- `processing/deduplicator.py` (lines 39–46) — `_is_cta_link()`; unchanged.
- `processing/deduplicator.py` (lines 56–75) — `_score_source()` current implementation.
  The `len(anchor)` tiebreaker is the suspected root of the WALL-E failure. Do not change
  until diagnostic confirms.
- `processing/deduplicator.py` (lines 78–114) — `_build_sources()`; the diagnostic script
  reproduces this loop with added verbose output.
- `ai/claude_client.py` (lines 13–58) — `_TOOL_SCHEMA` including summary description "2–4 sentences".
- `ai/claude_client.py` (lines 81–103) — `_build_user_message()`; sparse annotation is
  injected here inside the per-story loop.
- `scripts/inspect_sections.py` — structural template for `scripts/inspect_clusters.py`.
- `tests/test_deduplicator.py` — mirror existing test structure for new CTA tests.
- `tests/test_claude_client.py` — mirror existing test structure for sparse annotation tests.

### New Files to Create

- `scripts/inspect_clusters.py` — diagnostic script; no production impact.

### Patterns to Follow

**Constant naming** (mirror existing in `claude_client.py`):
```python
_SPARSE_CHUNK_THRESHOLD = 150   # total chars across all chunks in a story group
```

**Conditional constant** (only written if scoring change is confirmed):
```python
_ANCHOR_IDEAL_MAX_WORDS = 7     # anchors above this word count score 0 on quality
```

**CTA list format** (`deduplicator.py` line 13): lowercase substrings, grouped with inline
comment. New entries must follow the existing convention — substring match, case-insensitive
via `.lower()` in `_is_cta_link()`.

**Sparse annotation format**: inject a `<note>` XML element inside `## Story N`, after the
last `</source>` tag and before the blank separator line.

---

## IMPLEMENTATION PLAN

### Phase 1: CTA filter gap (confirmed fix)

**Location**: `processing/deduplicator.py`, lines 13–36 (`_CTA_ANCHOR_SIGNALS` tuple)

Add the following entries with inline comments:

```python
# Watch/view CTAs — "watch now" was confirmed missing (Deep View §15 Slack sponsor)
"watch now",
# Lead-gen / download CTAs from same family as existing entries
"get the report",
"download the report",
"get the guide",
"get the whitepaper",
# Sign-up variants not covered by "sign up free" / "sign up now"
"start free",
"start for free",
"start free trial",
# Demo/interactive
"see it in action",
```

**Why each entry**: "watch now" is the confirmed failure. The others complete the family of
patterns the existing list already targets ("try a demo", "sign up free", etc.). They are
not speculative — they are standard sponsor CTA patterns from the same newsletters that
produce the confirmed "watch now" miss.

**Risk**: None. `_build_sources()` already has a fallback (lines 99–100): if every link in
a chunk is a CTA, all links are used. New entries cannot produce empty attribution.

**Validation**:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.deduplicator import _is_cta_link
cases = [('Watch now', True), ('WATCH NOW', True), ('get the report', True), ('see it in action', True), ('Download the Report', True), ('Nvidia GTC keynote', False)]
for anchor, expected in cases:
    result = _is_cta_link({'anchor_text': anchor})
    status = 'OK' if result == expected else 'FAIL'
    print(f'  {status}: {anchor!r} -> {result} (expected {expected})')
"
```
Expected: all `OK`.

---

### Phase 2: Sparse input generation fix (confirmed fix)

**Two coordinated changes** — both required.

#### Change 2a — Tool schema summary description (`ai/claude_client.py`, lines ~38–42)

Before:
```python
"description": (
    "2–4 sentences capturing the most complete picture "
    "across all source versions. Prioritize clarity."
),
```

After:
```python
"description": (
    "1–4 sentences capturing the most complete picture "
    "across all source versions. For very short items, "
    "one sentence is acceptable. Prioritize clarity."
),
```

**Why**: The schema is Claude's formal contract. Without changing it, Claude may honor "2–4
sentences" as authoritative even when a per-story note grants permission to be brief. Changing
the lower bound to 1 removes the structural conflict.

**Risk**: No effect on normal story groups. Normal sections (200–600 chars) continue
producing 2–4 sentence summaries. The change removes a lower bound; it does not alter the
upper bound or expected behavior for well-sourced stories.

#### Change 2b — `_SPARSE_CHUNK_THRESHOLD` and sparse annotation (`ai/claude_client.py`)

Add constant after `_MAX_CHUNK_CHARS = 600` (line 16):
```python
_SPARSE_CHUNK_THRESHOLD = 150  # total chars across a story group's chunks; below = sparse
```

Inside `_build_user_message()`, after all `<source>` blocks for a story group and before the
blank separator line:
```python
total_chars = sum(len(chunk.text[:_MAX_CHUNK_CHARS]) for chunk in group.chunks)
if total_chars < _SPARSE_CHUNK_THRESHOLD:
    lines.append(
        "<note>Short item: only limited source text is available above. "
        "Write the best minimal entry you can from the text provided. "
        "A single-sentence summary is acceptable for short items. "
        "Do not return UNKNOWN or leave fields empty.</note>"
    )
```

**Why 150 chars**: After `_split_list_section()`, one-line roundup items produce 30–80 char
clean texts (confirmed from Deep View inspection). Normal sections passing `_MIN_SECTION_CHARS`
are 100+ chars, and typical sections after heading merge are 200+ chars. The gap between
~80 (largest one-liner after splitting) and ~200 (smallest typical section) is wide; 150
sits cleanly in the gap.

**Risk — annotation does not license invention**: The `<note>` gives permission to be brief;
it does not override the system prompt ("do not embellish beyond what sources contain"). A
one-line item will produce a one-sentence summary derived from the available text. This is
the intended outcome.

**Risk — count/order contract unchanged**: The annotation is injected inside `## Story N`
and does not alter the number of story groups or their order. The tool schema `entries` count
contract is unaffected.

---

### Phase 3: Diagnostic script — `scripts/inspect_clusters.py`

**Purpose**: For each of the three unconfirmed source-link failures ("WALL-E", "Google",
"manage all features"), determine definitively whether the failure is:
- **Scoring failure**: the correct chunk is in the cluster, but `_score_source()` selects
  the wrong link from that chunk's candidates.
- **Clustering false positive**: the wrong chunk is in the cluster; the anchor text comes
  from a section that covers a different story entirely.

This distinction determines whether Phase 4 (scoring change) applies at all.

**Structure**: Mirror `scripts/inspect_sections.py`. Accept a `.eml` CLI arg. Run the full
pipeline through `embed_and_cluster()` then `deduplicate()`. For each story group, print:

```
=== Story Group N (M chunks) ===
  Chunk 1 [sender: "Deep View"] (142 chars)
    Text preview: "Sam Altman tells students AGI will arrive before grad..."
    Candidate links (3):
      [Google] https://google.com/something  path_depth=2  word_count=1  score=(2,1)
      [OpenAI] https://openai.com/blog/agis  path_depth=3  word_count=1  score=(3,1)
      [Microsoft] https://microsoft.com/ai   path_depth=2  word_count=1  score=(2,1)
      CTA-filtered: 0
    WINNER: [OpenAI] https://openai.com/blog/agis
```

The output makes it immediately visible whether:
- The chunk belongs to the story (text preview confirms it) or is a stray section
- The correct link exists in the chunk but loses to a worse candidate
- Only one link survives the CTA filter (default winner with no competition)

**Implementation**: Import `parse_emails` from `ingestion.email_parser`; `embed_and_cluster`
from `processing.embedder`; `_is_cta_link`, `_score_source`, `_build_sources` from
`processing.deduplicator`. Parse the `.eml`, call `embed_and_cluster()`, then reproduce the
`_build_sources()` loop verbosely rather than calling it directly.

Note: `embed_and_cluster()` loads the sentence-transformers model on first call (~5s if not
cached).

**This script has no tests**. It is a diagnostic tool. Running it is a manual step after
Tasks 1–4 are complete.

---

### Phase 4: Conditional — `_score_source()` word-count cap

**Apply this phase ONLY if** the diagnostic output from Phase 3 shows that a wrong anchor
is winning because the correct chunk IS in the cluster but the scoring function prefers a
long prose anchor over a shorter headline.

**Do not apply** if the diagnostic shows the wrong chunk is in the cluster. That is a
clustering false positive and requires a separate investigation.

**If confirmed**: the specific failure pattern is that `len(anchor)` scores prose-length
in-text references (14+ words) above headline anchors (3–7 words) when both are at equal
path depth. The fix is:

```python
_ANCHOR_IDEAL_MAX_WORDS = 7
# Anchors with more words than this are treated as in-text prose references, not headlines.
# They score 0 on the quality dimension; path_depth alone determines selection among them.
# Within the headline range (≤7 words), longer (more descriptive) is better.

def _score_source(source: dict) -> tuple[int, int]:
    url = source.get("url", "")
    anchor = source.get("anchor_text", "")
    try:
        path = urlparse(url).path.rstrip("/")
        path_depth = len([s for s in path.split("/") if s])
    except Exception:
        path_depth = 0
    word_count = len(anchor.split())
    anchor_score = word_count if word_count <= _ANCHOR_IDEAL_MAX_WORDS else 0
    return (path_depth, anchor_score)
```

**Why 7 words**: Observed headline anchors in Deep View range from 3–7 words. The WALL-E
prose anchor is 14 words. "manage all of these features from one central hub" is 9 words.
A threshold of 7 keeps genuine headlines unpenalized and caps the two known long-prose
examples.

**Tradeoffs if applied**:
- Path depth remains the dominant sort key. A penalized anchor at path_depth=3 still
  beats an unpenalized anchor at path_depth=2. This is correct: URL specificity is a
  stronger signal than anchor length.
- Among anchors that are all penalized (all > 7 words), the tiebreak is arbitrary.
  Both were prose phrases; the outcome quality is equivalent.
- An 8-word legitimate headline (e.g., "Anthropic Doubles Claude Usage Outside Peak Hours
  For Free" = 9 words) would be penalized. If it is the only non-CTA link in its chunk,
  it still wins by default (scores 0 but has no competitor). If it competes with a 5-word
  anchor at the same depth, it loses — which may be wrong in a small number of cases.
  This is a known tradeoff of using a hard threshold.

**Scoring tests to add if this phase is applied** (in `tests/test_deduplicator.py`):
- `test_score_source_prose_anchor_penalized` — 14-word anchor returns `(path_depth, 0)`
- `test_score_source_headline_beats_prose_at_same_depth` — 5-word vs 14-word at same depth; 5-word wins
- `test_score_source_short_anchor_uncapped` — 5-word → anchor_score == 5
- `test_score_source_boundary_at_seven_words` — exactly 7 words → score == 7; 8 words → score == 0
- `test_score_source_path_depth_still_primary` — 14-word at depth=3 beats 5-word at depth=2

---

## STEP-BY-STEP TASKS

### TASK 1 — UPDATE `processing/deduplicator.py`: add CTA signals (confirmed)

- **ADD**: New entries to `_CTA_ANCHOR_SIGNALS` tuple (lines 13–36)
- **ENTRIES**: `"watch now"`, `"see it in action"`, `"get the report"`, `"download the report"`, `"get the guide"`, `"get the whitepaper"`, `"start free"`, `"start for free"`, `"start free trial"`
- **PATTERN**: Match existing tuple structure; add inline comment grouping entries by type
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_deduplicator.py -v 2>&1 | tail -20`

### TASK 2 — UPDATE `ai/claude_client.py`: sparse threshold constant and schema fix (confirmed)

- **ADD**: Constant `_SPARSE_CHUNK_THRESHOLD = 150` after `_MAX_CHUNK_CHARS = 600` (line 16)
- **UPDATE**: `_TOOL_SCHEMA` summary description: `"2–4 sentences"` → `"1–4 sentences"` with appended `" For very short items, one sentence is acceptable."`
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_claude_client.py -v 2>&1 | tail -20`

### TASK 3 — UPDATE `ai/claude_client.py`: sparse annotation in `_build_user_message()` (confirmed)

- **UPDATE**: `_build_user_message()` story group loop — compute `total_chars`; inject `<note>` block for sparse groups
- **PATTERN**: After all `</source>` lines for a group, before `lines.append("")` separator
- **GOTCHA**: `lines.append("")` is the blank line between story groups; the note must go BEFORE it so it stays scoped to the story, not the separator
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_claude_client.py -v 2>&1 | tail -30`

### TASK 4 — ADD tests: `tests/test_deduplicator.py` (CTA gaps only)

- **ADD**: 4 CTA gap tests: `test_cta_watch_now_filtered`, `test_cta_watch_now_case_insensitive`, `test_cta_get_the_report_filtered`, `test_cta_see_it_in_action_filtered`
- **DO NOT** add scoring tests yet — those are gated on Phase 4 diagnostic confirmation
- **PATTERN**: Mirror existing `_is_cta_link` test structure
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_deduplicator.py -v 2>&1 | tail -30`

### TASK 5 — ADD tests: `tests/test_claude_client.py` (sparse annotation)

- **ADD**: 4 sparse annotation tests as specified in Phase 2
- **IMPORTS**: Add `_SPARSE_CHUNK_THRESHOLD` to imports; add `StoryGroup` from `processing.deduplicator`, `StoryChunk` from `processing.embedder` for fixture construction
- **GOTCHA**: Check exact `StoryChunk` field names against the dataclass definition before writing tests
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_claude_client.py -v 2>&1 | tail -30`

### TASK 6 — RUN full test suite

- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -40`

### TASK 7 — CREATE `scripts/inspect_clusters.py`

- **CREATE**: New diagnostic script following structure of `scripts/inspect_sections.py`
- **IMPLEMENT**: Accept `.eml` CLI arg; parse, embed, cluster, deduplicate; for each story
  group print chunks with text previews and per-link scores showing path_depth, word_count,
  final score, CTA filter result, and winner
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python scripts/inspect_clusters.py 2>&1 | head -3`
  Expected: usage line, no ImportError

### TASK 8 (CONDITIONAL) — Run diagnostic against Deep View sample

After Task 7:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && \
  .venv/bin/python scripts/inspect_clusters.py debug_samples/deep_view_sample.eml 2>/dev/null
```

For each of the three unconfirmed failures, inspect the output and document:

**For "WALL-E" anchor** (story: "Anthropic also courts private equity..."):
- Is the chunk text a continuation of the Nvidia robotics story or the Anthropic PE story?
  - If robotics text → clustering false positive → Phase 4 does not apply; defer
  - If Anthropic PE text → scoring failure → Phase 4 applies

**For "Google" anchor** (story: "Sam Altman tells students AGI..."):
- Is the chunk text AGI/Altman content or Nvidia space/Google content?
  - If Nvidia/space content → clustering false positive → Phase 4 does not apply; defer
  - If AGI content but only "Google" link in chunk → source poverty; neither scoring nor clustering; defer
  - If AGI content with better link that lost to "Google" → scoring failure → Phase 4 applies

**For "manage all features" anchor** (story: "Meta commits $27B to Nebius..."):
- Is the chunk text about Nebius/Meta or about Airia (sponsor)?
  - If Airia sponsor text → clustering false positive → Phase 4 does not apply; defer
  - If Nebius/Meta text but Airia link → scoring failure → Phase 4 applies

**Decision rule**: Phase 4 is applied only for failures confirmed as scoring failures in the
above analysis. If all three are clustering false positives, Phase 4 is skipped entirely.

### TASK 9 (CONDITIONAL) — Apply `_score_source()` word-count cap if confirmed

Only if Task 8 identifies at least one confirmed scoring failure:

- **ADD**: Constant `_ANCHOR_IDEAL_MAX_WORDS = 7` after `_is_cta_link()` in `deduplicator.py`
- **UPDATE**: `_score_source()` — replace `return (path_depth, len(anchor))` with word-count-capped version
- **ADD**: 5 scoring tests to `tests/test_deduplicator.py`
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_deduplicator.py -v 2>&1 | tail -30`

---

## TESTING STRATEGY

### Unit Tests (unconditional)

4 CTA gap tests + 4 sparse annotation tests. All use plain functions, direct asserts,
no mocks. Scoring tests are added only if Phase 4 is confirmed by the diagnostic.

### Edge Cases (unconditional)

- Anchor exactly at `_ANCHOR_IDEAL_MAX_WORDS` words — not penalized (boundary inclusive)
- Anchor exactly at `_ANCHOR_IDEAL_MAX_WORDS + 1` words — penalized (first over boundary)
  (These tests are only written if Phase 4 is confirmed.)
- Chunk with total chars exactly at `_SPARSE_CHUNK_THRESHOLD - 1` — gets annotation
- Chunk with total chars exactly at `_SPARSE_CHUNK_THRESHOLD` — no annotation

### What is NOT tested by unit tests

The actual Claude API response for sparse inputs. The annotation is tested structurally
(does the `<note>` string appear in the prompt?). Whether Claude produces non-UNKNOWN output
is validated in the manual post-fix run.

---

## VALIDATION COMMANDS

### Level 1: CTA filter check (after Task 1)
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.deduplicator import _is_cta_link
cases = [('Watch now', True), ('WATCH NOW', True), ('get the report', True), ('see it in action', True), ('Download the Report', True), ('Nvidia GTC keynote', False)]
for anchor, expected in cases:
    result = _is_cta_link({'anchor_text': anchor})
    status = 'OK' if result == expected else 'FAIL'
    print(f'  {status}: {anchor!r} -> {result} (expected {expected})')
"
```

### Level 2: Sparse threshold and schema check (after Tasks 2–3)
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ai.claude_client import _SPARSE_CHUNK_THRESHOLD, _TOOL_SCHEMA
print(f'_SPARSE_CHUNK_THRESHOLD = {_SPARSE_CHUNK_THRESHOLD}')
summary_desc = _TOOL_SCHEMA['input_schema']['properties']['entries']['items']['properties']['summary']['description']
print(f'summary description: {summary_desc!r}')
assert summary_desc.startswith('1\u20134 sentences'), 'FAIL: schema still says 2-4 sentences'
print('  OK: schema starts with 1-4 sentences')
"
```

### Level 3: Unit tests (after Tasks 4–5)
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -50
```

### Level 4: Diagnostic script smoke test (after Task 7)
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python scripts/inspect_clusters.py 2>&1 | head -3
```
Expected: usage message, no ImportError or SyntaxError.

### Level 5: Scoring fix check (after Task 9, only if Phase 4 applied)
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.deduplicator import _score_source, _ANCHOR_IDEAL_MAX_WORDS
print(f'_ANCHOR_IDEAL_MAX_WORDS = {_ANCHOR_IDEAL_MAX_WORDS}')
cases = [
    ('WALL-E prose (14w)', 'https://example.com/robots/keynote', 'small robots that looked like they came straight out of WALL-E'),
    ('5w headline (same depth)', 'https://example.com/robots/keynote', 'Nvidia GTC robotics keynote'),
    ('Boundary 7w', 'https://example.com/a/b', 'one two three four five six seven'),
    ('Over boundary 8w', 'https://example.com/a/b', 'one two three four five six seven eight'),
]
for label, url, anchor in cases:
    s = _score_source({'url': url, 'anchor_text': anchor})
    print(f'  {label}: {s}')
"
```
Expected: 5-word headline `(2, 5)` > WALL-E `(2, 0)` at equal path depth; boundary 7w = `(1, 7)`, boundary+1 = `(1, 0)`.

---

## MANUAL VERIFICATION CHECKLIST

After the confirmed fixes (Tasks 1–7) are implemented, run a real Deep View digest:

- [ ] Search output for literal string "UNKNOWN" — expected: zero occurrences.
- [ ] Find a short roundup item (e.g., "Mistral introduces Leanstral") — confirm `summary`
  field contains a real sentence, not empty string, not `<UNKNOWN>`.
- [ ] Confirm §15 Slack sponsor no longer appears as source for a non-Slack story (no "Watch now" anchor in final sources).
- [ ] Confirm normal full-length story summaries still produce 2+ sentences (no regression).
- [ ] Run `scripts/inspect_clusters.py` against the Deep View sample and document the root
  cause of each unconfirmed failure per the decision rule in Task 8.

After Task 9 (if applied):
- [ ] Confirm "small robots that looked like they came straight out of WALL-E" no longer
  appears as a source anchor.

---

## ROLLBACK CONSIDERATIONS

All changes are localized to two source files and two test files. No schema migrations, no
new dependencies, no config changes. Rollback:
- Revert `_CTA_ANCHOR_SIGNALS` entries
- Revert sparse annotation constant and `_build_user_message()` annotation block
- Revert tool schema summary description
- If Phase 4 was applied: revert `_score_source()` and remove `_ANCHOR_IDEAL_MAX_WORDS`

`scripts/inspect_clusters.py` has no production impact and can remain or be removed.

---

## ACCEPTANCE CRITERIA

**Unconditional (Tasks 1–7):**
- [ ] `_is_cta_link({"anchor_text": "Watch now"})` returns `True`
- [ ] `_SPARSE_CHUNK_THRESHOLD == 150`
- [ ] Tool schema summary description starts with `"1–4 sentences"`
- [ ] `_build_user_message()` includes `<note>` for groups with total chars < 150
- [ ] `_build_user_message()` does NOT include `<note>` for groups with total chars ≥ 150
- [ ] All existing tests pass (no regressions)
- [ ] All new unit tests pass
- [ ] `scripts/inspect_clusters.py` runs without import errors

**Conditional (Task 9, only if Phase 4 confirmed):**
- [ ] `_score_source()` for a 14-word anchor returns a tuple whose second element is `0`
- [ ] `_score_source()` for a 5-word anchor beats a 14-word anchor at the same path depth

---

## NOTES

### Why the diagnostic gate matters

The three unconfirmed failures share a surface symptom (wrong anchor) but may have different
root causes. A scoring change applied to a clustering false positive would add complexity to
`_score_source()` without actually fixing the failure. The diagnostic script makes the root
cause observable before any decision is made.

### Why "Watch now" is confirmed without a diagnostic

"Watch now" is structurally identical to the already-confirmed CTA patterns in `_CTA_ANCHOR_SIGNALS`.
Its absence is a gap in an existing, confirmed strategy — not a new strategy being introduced.
No diagnostic is needed to confirm that a button labeled "Watch now" in a sponsor block is a CTA.

### On deferring clustering false positives

If the diagnostic shows that one or more failures are clustering false positives, that will
be surfaced as a distinct finding. Fixing false positive clustering is out of scope for this
loop: it requires inspecting the dedup threshold, the embedding behavior for continuation
sections, or the section-level structure. It is a separate investigation, not a scoring patch.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

### Level 1: CTA filter
Command:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.deduplicator import _is_cta_link
cases = [('Watch now', True), ('WATCH NOW', True), ('get the report', True), ('see it in action', True), ('Download the Report', True), ('Nvidia GTC keynote', False)]
for anchor, expected in cases:
    result = _is_cta_link({'anchor_text': anchor})
    status = 'OK' if result == expected else 'FAIL'
    print(f'  {status}: {anchor!r} -> {result} (expected {expected})')
"
```
Expected output:
```
  OK: 'Watch now' -> True (expected True)
  OK: 'WATCH NOW' -> True (expected True)
  OK: 'get the report' -> True (expected True)
  OK: 'see it in action' -> True (expected True)
  OK: 'Download the Report' -> True (expected True)
  OK: 'Nvidia GTC keynote' -> False (expected False)
```

### Level 2: Sparse threshold and schema
Command:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ai.claude_client import _SPARSE_CHUNK_THRESHOLD, _TOOL_SCHEMA
print(f'_SPARSE_CHUNK_THRESHOLD = {_SPARSE_CHUNK_THRESHOLD}')
summary_desc = _TOOL_SCHEMA['input_schema']['properties']['entries']['items']['properties']['summary']['description']
print(f'summary description: {summary_desc!r}')
assert summary_desc.startswith('1\u20134 sentences'), 'FAIL: schema still says 2-4 sentences'
print('  OK: schema starts with 1-4 sentences')
"
```
Expected output:
```
_SPARSE_CHUNK_THRESHOLD = 150
summary description: '1–4 sentences capturing the most complete picture across all source versions. For very short items, one sentence is acceptable. Prioritize clarity.'
  OK: schema starts with 1-4 sentences
```

### Level 3: Unit test suite
Command:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```
Expected: all tests pass, 0 failures, count ≥ 47.

### Level 4: Diagnostic script smoke test
Command:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python scripts/inspect_clusters.py 2>&1 | head -3
```
Expected: prints usage line (e.g. `Usage: python scripts/inspect_clusters.py path/to/email.eml`), exits non-zero but no ImportError or SyntaxError.

### Level 5: Scoring fix check (only if Phase 4 applied)
Command:
```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.deduplicator import _score_source, _ANCHOR_IDEAL_MAX_WORDS
print(f'_ANCHOR_IDEAL_MAX_WORDS = {_ANCHOR_IDEAL_MAX_WORDS}')
cases = [
    ('WALL-E prose (14w)', 'https://example.com/robots/keynote', 'small robots that looked like they came straight out of WALL-E'),
    ('5w headline (same depth)', 'https://example.com/robots/keynote', 'Nvidia GTC robotics keynote'),
    ('Boundary 7w', 'https://example.com/a/b', 'one two three four five six seven'),
    ('Over boundary 8w', 'https://example.com/a/b', 'one two three four five six seven eight'),
]
for label, url, anchor in cases:
    s = _score_source({'url': url, 'anchor_text': anchor})
    print(f'  {label}: {s}')
"
```
Expected:
```
_ANCHOR_IDEAL_MAX_WORDS = 7
  WALL-E prose (14w): (2, 0)
  5w headline (same depth): (2, 5)
  Boundary 7w: (1, 7)
  Over boundary 8w: (1, 0)
```

### Manual: no `<UNKNOWN>` in next Deep View digest
After running a real digest: search returned JSON or rendered output for literal string `UNKNOWN`. Expected: zero occurrences.

### Manual: short roundup item produces valid summary
After running a real digest: find a roundup item (any one-line bullet from Deep View). Expected: `summary` field contains a real sentence, not empty string, not `<UNKNOWN>`.

### Manual: no "Watch now" source anchor
After running a real digest: search all `sources[].anchor_text` values for "Watch now" or "watch now". Expected: zero occurrences.

### Manual: normal summaries unaffected
After running a real digest: select any story whose source text is > 200 chars. Expected: `summary` field contains 2 or more sentences.

### Manual: `scripts/inspect_clusters.py` diagnostic output documented
Run against Deep View sample. For each of the three unconfirmed failures, note whether the
root cause is confirmed as a scoring failure or a clustering false positive per the decision
rule in Task 8. Expected: findings documented; Phase 4 decision made.
