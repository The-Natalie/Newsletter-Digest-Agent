# Feature: ai/claude_client.py

The following plan should be complete, but validate documentation and codebase patterns before starting.

Pay special attention to: the exact tool schema shape (entries array WITHOUT sources — sources pass through from StoryGroup), the async client initialization pattern, and the strict ordering contract between the Claude response entries and the input story_groups list.

## Feature Description

Create `ai/claude_client.py` — the Anthropic SDK wrapper that takes a list of `StoryGroup` objects and a folder name, builds a batched multi-cluster prompt, calls Claude with a forced tool-use response, and returns a list of structured digest entry dicts (headline + summary + significance + sources). This is the AI generation stage of the pipeline — the final transformation before the digest JSON is written to the database.

## User Story

As the digest pipeline,
I want a function that takes story groups and a folder name and returns structured digest entries,
So that each deduplicated story cluster becomes a formatted headline + summary + significance ready for display.

## Problem Statement

`deduplicate()` returns `list[StoryGroup]`, each carrying story text excerpts and source links. Without a client module, the pipeline has no way to turn those excerpts into a human-readable digest. `ai/claude_client.py` bridges the gap: it constructs a batched prompt that presents all story groups to Claude in a single API call (cost-efficient), forces structured JSON output via tool use, and merges Claude's text-only response with the pre-built source links from `StoryGroup.sources`.

## Scope

- In scope: `ai/__init__.py` (empty), `ai/claude_client.py` — tool schema, prompt builder, async generate function, empty-input guard, error logging
- Out of scope: rate limiting/retry logic (Phase 2), streaming, per-story individual API calls, caching

## Solution Statement

Use `AsyncAnthropic` (lazy-initialized module-level client) to call `messages.create()` with a single batched multi-cluster prompt. Force tool use via `tool_choice={"type": "tool", "name": "create_digest_entries"}`. The tool schema returns `{"entries": [{headline, summary, significance}]}` — sources are deliberately excluded from the schema and merged back in from `StoryGroup.sources` after the response. This keeps URLs and newsletter attribution out of Claude's hands, preventing hallucinated or corrupted links.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Medium
**Primary Systems Affected**: `ai/claude_client.py`
**Dependencies**: `anthropic` SDK (async), `config.settings.claude_model`, `config.settings.anthropic_api_key`, `processing.deduplicator.StoryGroup`, `processing.embedder.StoryChunk`
**Assumptions**:
- `anthropic` package is already in `requirements.txt`
- `settings.anthropic_api_key` is the Anthropic API key string (not auto-read from env by the SDK — we pass it explicitly)
- `story_groups` entries are ordered; Claude must return entries in the same order (enforced via prompt wording)
- `max_tokens=8192` is sufficient for up to ~25 story entries with haiku

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `processing/deduplicator.py` (lines 11–15) — `StoryGroup` dataclass: `chunks: list[StoryChunk]` and `sources: list[dict]`; import from here
- `processing/embedder.py` (lines 24–28) — `StoryChunk` dataclass: `text: str`, `sender: str`, `links: list[dict]`; referenced via StoryGroup.chunks
- `config.py` (lines 14–15) — `settings.anthropic_api_key: str`, `settings.claude_model: str` (default `"claude-haiku-4-5"`)
- `ingestion/imap_client.py` (lines 1–8) — module-level imports and `from config import settings` pattern
- `ingestion/email_parser.py` (lines 1–13) — establishes module pattern: `from __future__ import annotations`, `logger = logging.getLogger(__name__)`, module-level constants

### New Files to Create

- `ai/__init__.py` — empty package marker
- `ai/claude_client.py` — full implementation: lazy client, tool schema, prompt builder, `generate_digest()`

### Relevant Documentation — READ BEFORE IMPLEMENTING

- Anthropic Python SDK — AsyncAnthropic instantiation:
  ```python
  from anthropic import AsyncAnthropic
  client = AsyncAnthropic(api_key="...")
  ```
- Tool use forced response pattern:
  ```python
  response = await client.messages.create(
      model="...", max_tokens=..., system="...",
      messages=[{"role": "user", "content": "..."}],
      tools=[TOOL_SCHEMA],
      tool_choice={"type": "tool", "name": TOOL_NAME},
  )
  ```
- Parsing tool use response:
  ```python
  for block in response.content:
      if block.type == "tool_use":
          data = block.input   # already a dict, not JSON string
  ```
- anthropic error types: `anthropic.APIError` (base), `anthropic.RateLimitError`, `anthropic.APIConnectionError`, `anthropic.AuthenticationError`

### Patterns to Follow

**Module structure** (mirror `ingestion/email_parser.py` lines 1–5):
```python
from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from config import settings
from processing.deduplicator import StoryGroup

logger = logging.getLogger(__name__)
```

**Module-level constants** (mirror `processing/embedder.py` lines 15–19):
```python
_TOOL_NAME = "create_digest_entries"
_MAX_TOKENS = 8192
_MAX_CHUNK_CHARS = 600   # chars fed to prompt per story chunk (title + first 2-3 sentences)
```

**Lazy client** (mirror `processing/embedder.py` lines 21–37 `_get_model()` pattern):
```python
_client: AsyncAnthropic | None = None

def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client
```

**Logging** (mirror `processing/deduplicator.py` lines 66–70):
```python
logger.info("Calling Claude (%s) with %d story groups", settings.claude_model, len(story_groups))
logger.info("Claude returned %d digest entries", len(entries))
```

---

## IMPLEMENTATION PLAN

### Phase 1: Data model — tool schema and constants

Define the tool schema that Claude must respond with. `entries` is the only property — headline, summary, and significance per entry. Sources are NOT in the schema.

### Phase 2: Prompt builder

Two private functions:
- `_system_prompt(folder)` — returns system string referencing the folder name
- `_build_user_message(story_groups, folder)` — constructs the batched XML-style multi-cluster user message

### Phase 3: Core async function

`generate_digest(story_groups, folder)` — calls Claude, parses tool response, merges with `StoryGroup.sources`, returns `list[dict]`.

---

## STEP-BY-STEP TASKS

### TASK 1 — CREATE `ai/__init__.py`

- **IMPLEMENT**: Empty file (package marker only)
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import ai; print('ai package OK')"`

---

### TASK 2 — CREATE `ai/claude_client.py`

This is a single-file module. All sub-tasks build the same file in order.

#### 2a — Imports, constants, tool schema

- **IMPORTS**:
  ```python
  from __future__ import annotations

  import logging

  import anthropic
  from anthropic import AsyncAnthropic

  from config import settings
  from processing.deduplicator import StoryGroup

  logger = logging.getLogger(__name__)
  ```
- **CONSTANTS**:
  ```python
  _TOOL_NAME = "create_digest_entries"
  _MAX_TOKENS = 8192
  _MAX_CHUNK_CHARS = 600
  ```
- **TOOL SCHEMA** (module-level dict):
  ```python
  _TOOL_SCHEMA: dict = {
      "name": _TOOL_NAME,
      "description": (
          "Return one digest entry per story group, in the same order as the input. "
          "Do not invent or modify source links — sources are provided separately."
      ),
      "input_schema": {
          "type": "object",
          "properties": {
              "entries": {
                  "type": "array",
                  "description": "Digest entries in the same order as the story groups.",
                  "items": {
                      "type": "object",
                      "properties": {
                          "headline": {
                              "type": "string",
                              "description": "Clear and direct headline, max 12 words.",
                          },
                          "summary": {
                              "type": "string",
                              "description": (
                                  "2–4 sentences capturing the most complete picture "
                                  "across all source versions. Prioritize clarity."
                              ),
                          },
                          "significance": {
                              "type": "string",
                              "description": (
                                  "One sentence on why this matters for someone "
                                  "following the given topic area."
                              ),
                          },
                      },
                      "required": ["headline", "summary", "significance"],
                  },
              }
          },
          "required": ["entries"],
      },
  }
  ```
- **GOTCHA**: `sources` must NOT be in `_TOOL_SCHEMA`. Claude cannot reliably reproduce URLs; all source attribution comes from `StoryGroup.sources` built by `_build_sources()` in deduplicator.py.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ai.claude_client import _TOOL_SCHEMA, _TOOL_NAME; print('schema OK'); print(_TOOL_SCHEMA['input_schema']['properties']['entries']['items']['required'])"`

#### 2b — Lazy client helper

- **IMPLEMENT**:
  ```python
  _client: AsyncAnthropic | None = None


  def _get_client() -> AsyncAnthropic:
      """Lazy-initialize and cache the AsyncAnthropic client."""
      global _client
      if _client is None:
          logger.info("Initializing AsyncAnthropic client (model=%s)", settings.claude_model)
          _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
      return _client
  ```
- **GOTCHA**: Pass `api_key=settings.anthropic_api_key` explicitly — don't rely on env-var auto-detection, since `settings` already validates the key at startup.
- **PATTERN**: Mirror `_get_model()` in `processing/embedder.py` lines 31–37.

#### 2c — System prompt function

- **IMPLEMENT**:
  ```python
  def _system_prompt(folder: str) -> str:
      return (
          f"You are generating a newsletter digest focused on {folder}. "
          "For each story group, write a concise digest entry. "
          "Be factual and direct. Do not embellish or add information not present in the sources. "
          "Produce exactly as many entries as story groups provided, in the same order."
      )
  ```

#### 2d — User message builder

- **IMPLEMENT**:
  ```python
  def _build_user_message(story_groups: list[StoryGroup], folder: str) -> str:
      """Build the batched multi-cluster user prompt."""
      lines: list[str] = [
          f"Below are {len(story_groups)} story group(s). "
          f"Each group contains excerpts from one or more newsletters covering the same story. "
          f"Generate one digest entry per group, in order.\n"
      ]

      for i, group in enumerate(story_groups, 1):
          lines.append(f"## Story {i}")
          for chunk in group.chunks:
              excerpt = chunk.text[:_MAX_CHUNK_CHARS]
              lines.append(f'<source newsletter="{chunk.sender}">')
              lines.append(excerpt)
              lines.append("</source>")
          lines.append("")

      lines.append(
          f"Use the `{_TOOL_NAME}` tool to return {len(story_groups)} entries "
          f"(headline, summary, significance) in the same order as the stories above. "
          f"Each significance sentence should explain why this matters for someone following {folder}."
      )
      return "\n".join(lines)
  ```
- **GOTCHA**: `chunk.text[:_MAX_CHUNK_CHARS]` — always truncate chunks. Long newsletter bodies (>2000 chars) would inflate input tokens significantly with no benefit to summary quality.

#### 2e — Main `generate_digest()` function

- **IMPLEMENT**:
  ```python
  async def generate_digest(story_groups: list[StoryGroup], folder: str) -> list[dict]:
      """Call Claude to generate digest entries for all story groups in one API call.

      Args:
          story_groups: List of StoryGroup objects from deduplicate().
          folder: IMAP folder name used as topic context in the prompt.

      Returns:
          List of digest entry dicts, one per story group, each containing:
          {"headline": str, "summary": str, "significance": str, "sources": list[dict]}
          Returns [] if story_groups is empty.

      Raises:
          anthropic.APIError: On any Anthropic API failure. Let callers handle retries.
      """
      if not story_groups:
          return []

      client = _get_client()
      user_message = _build_user_message(story_groups, folder)

      logger.info(
          "Calling Claude (%s) with %d story group(s) for folder '%s'",
          settings.claude_model,
          len(story_groups),
          folder,
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
          logger.error("Claude API error: %s", exc)
          raise

      # Extract tool input from the response
      tool_input: dict | None = None
      for block in response.content:
          if block.type == "tool_use":
              tool_input = block.input
              break

      if tool_input is None:
          raise ValueError(
              f"Claude response contained no tool_use block. "
              f"stop_reason={response.stop_reason!r}"
          )

      raw_entries: list[dict] = tool_input.get("entries", [])
      logger.info("Claude returned %d digest entry/entries", len(raw_entries))

      if len(raw_entries) != len(story_groups):
          logger.warning(
              "Entry count mismatch: Claude returned %d entries for %d story groups — "
              "truncating/padding to match",
              len(raw_entries),
              len(story_groups),
          )

      # Merge Claude's text fields with pre-built source attribution from deduplicator
      result: list[dict] = []
      for entry, group in zip(raw_entries, story_groups):
          result.append({
              "headline": entry.get("headline", ""),
              "summary": entry.get("summary", ""),
              "significance": entry.get("significance", ""),
              "sources": group.sources,
          })

      return result
  ```
- **GOTCHA**: `zip(raw_entries, story_groups)` silently handles count mismatches (truncates to the shorter list). The logger.warning above surfaces the mismatch without crashing the pipeline.
- **GOTCHA**: `tool_input` from `block.input` is already a Python dict — do NOT call `json.loads()` on it.
- **GOTCHA**: `anthropic.APIError` is the base class. Let it propagate to `digest_builder.py` which will catch it and write `status="failed"` to the DB.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import inspect, asyncio; from ai.claude_client import generate_digest; print('async:', asyncio.iscoroutinefunction(generate_digest)); print('sig:', inspect.signature(generate_digest))"`

---

## TESTING STRATEGY

No separate test file required. Validation uses synthetic fixtures without live API calls (Levels 1–3), plus an optional live call (Level 4).

### Unit Tests (inline validation)

- Import and schema structure
- `_build_user_message()` output contains expected XML tags and story count instructions
- Empty input guard returns `[]` without calling Claude

### Edge Cases

- `story_groups=[]` → returns `[]` (no API call made)
- Claude returns fewer entries than story groups → warning logged, result truncated to shorter list
- Claude returns tool response with missing fields → `.get()` defaults to `""`
- `_MAX_CHUNK_CHARS` truncates long excerpts before they reach the prompt

---

## VALIDATION COMMANDS

### Level 1: Package and import check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import ai; from ai.claude_client import generate_digest, _TOOL_SCHEMA, _TOOL_NAME, _build_user_message; print('all imports OK')"
```
Expected output:
```
all imports OK
```

### Level 2: Tool schema structure check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ai.claude_client import _TOOL_SCHEMA, _TOOL_NAME
assert _TOOL_SCHEMA['name'] == _TOOL_NAME
schema = _TOOL_SCHEMA['input_schema']
assert schema['type'] == 'object'
assert 'entries' in schema['properties']
item = schema['properties']['entries']['items']
assert set(item['required']) == {'headline', 'summary', 'significance'}, f'required={item[\"required\"]}'
assert 'sources' not in item['properties'], 'sources must NOT be in tool schema'
print('Tool schema check PASSED')
print('entry required fields:', item['required'])
"
```
Expected output:
```
Tool schema check PASSED
entry required fields: ['headline', 'summary', 'significance']
```

### Level 3: Prompt builder and empty-input dry-run

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import asyncio
from processing.embedder import StoryChunk
from processing.deduplicator import StoryGroup
from ai.claude_client import _build_user_message, generate_digest

chunk1 = StoryChunk(text='OpenAI launches GPT-5.', sender='TLDR AI', links=[])
chunk2 = StoryChunk(text='OpenAI releases GPT-5 today.', sender='The Rundown', links=[])
group1 = StoryGroup(chunks=[chunk1, chunk2], sources=[])
group2 = StoryGroup(chunks=[StoryChunk(text='Climate summit concluded.', sender='BBC', links=[])], sources=[])

msg = _build_user_message([group1, group2], 'AI Newsletters')
assert '## Story 1' in msg, 'Missing Story 1 header'
assert '## Story 2' in msg, 'Missing Story 2 header'
assert 'newsletter=\"TLDR AI\"' in msg, 'Missing TLDR AI source tag'
assert 'newsletter=\"The Rundown\"' in msg, 'Missing The Rundown source tag'
assert '2 entries' in msg or '2 story group' in msg, f'Missing count in prompt: {msg[-200:]}'
print('Prompt builder check PASSED')
print('Prompt length (chars):', len(msg))

# Empty input guard — must NOT call Claude
result = asyncio.run(generate_digest([], 'AI Newsletters'))
assert result == [], f'Expected [], got {result}'
print('Empty input guard PASSED')
"
```
Expected output:
```
Prompt builder check PASSED
Prompt length (chars): <some number>
Empty input guard PASSED
```

### Level 4: Live API call (requires valid ANTHROPIC_API_KEY in .env)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import asyncio
from processing.embedder import StoryChunk
from processing.deduplicator import StoryGroup
from ai.claude_client import generate_digest

chunk1 = StoryChunk(
    text='OpenAI has launched GPT-5, a major new language model with improved reasoning and multimodal capabilities. The release was announced on March 14, 2026.',
    sender='TLDR AI',
    links=[{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}],
)
chunk2 = StoryChunk(
    text='OpenAI released GPT-5 today, marking a significant step in AI development. The model supports images, audio, and text natively.',
    sender='The Rundown AI',
    links=[{'url': 'https://therundown.ai/p/gpt5', 'anchor_text': 'GPT-5 is here'}],
)
group = StoryGroup(
    chunks=[chunk1, chunk2],
    sources=[
        {'newsletter': 'TLDR AI', 'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'},
        {'newsletter': 'The Rundown AI', 'url': 'https://therundown.ai/p/gpt5', 'anchor_text': 'GPT-5 is here'},
    ],
)

entries = asyncio.run(generate_digest([group], 'AI Newsletters'))
print('Entry count:', len(entries))
print('Keys:', list(entries[0].keys()))
print('Headline:', entries[0]['headline'])
print('Summary (first 100 chars):', entries[0]['summary'][:100])
print('Significance (first 100 chars):', entries[0]['significance'][:100])
print('Sources:', entries[0]['sources'])
assert len(entries) == 1
assert set(entries[0].keys()) == {'headline', 'summary', 'significance', 'sources'}
assert entries[0]['sources'] == group.sources
print('Live API test PASSED')
"
```
Expected output (values will vary — verify structure):
```
Entry count: 1
Keys: ['headline', 'summary', 'significance', 'sources']
Headline: <12-word-or-less headline about GPT-5>
Summary (first 100 chars): <factual 2-4 sentence summary>
Significance (first 100 chars): <one sentence on why this matters>
Sources: [{'newsletter': 'TLDR AI', 'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}, {'newsletter': 'The Rundown AI', 'url': 'https://therundown.ai/p/gpt5', 'anchor_text': 'GPT-5 is here'}]
Live API test PASSED
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `ai/__init__.py` exists
- [ ] `ai/claude_client.py` exists
- [ ] All Level 1–3 validations pass (no API key required)
- [ ] `_TOOL_SCHEMA` does NOT contain `sources` in the item properties
- [ ] `generate_digest([])` returns `[]` without making any API call
- [ ] Prompt output contains `<source newsletter="...">` XML tags for each chunk
- [ ] Level 4 live call produces `headline`, `summary`, `significance`, and `sources` keys (requires valid ANTHROPIC_API_KEY)

## ROLLBACK CONSIDERATIONS

- New files only; rollback = delete `ai/__init__.py` and `ai/claude_client.py`
- No database changes, migrations, or config changes required

## ACCEPTANCE CRITERIA

- [ ] `generate_digest(story_groups, folder)` is `async` and returns `list[dict]`
- [ ] Each dict has exactly `headline`, `summary`, `significance`, `sources` keys
- [ ] `sources` values come from `StoryGroup.sources`, NOT from Claude
- [ ] All story groups are sent in a single Claude API call (no per-story calls)
- [ ] Tool use is forced via `tool_choice={"type": "tool", "name": _TOOL_NAME}`
- [ ] `anthropic.APIError` propagates to the caller (not swallowed)
- [ ] Entry count mismatch triggers a `logger.warning`, not an exception
- [ ] `generate_digest([])` returns `[]` without calling the API
- [ ] All Levels 1–3 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1: `ai/__init__.py` created
- [ ] Task 2: `ai/claude_client.py` created with all components
- [ ] Level 1 validation passed
- [ ] Level 2 validation passed
- [ ] Level 3 validation passed
- [ ] Level 4 validation passed (if API key available) or skipped with documented reason

---

## NOTES

**Why sources are excluded from the tool schema:**
Claude cannot reliably reproduce URLs — it may hallucinate, truncate, or slightly alter them. The `StoryGroup.sources` list was built deterministically from the raw email link data by `_build_sources()` in `deduplicator.py`. Merging after the API call is the only safe approach.

**Why one batched call instead of N individual calls:**
Cost efficiency (PRD §2 Core Principle 4). With haiku at ~$0.25 output/MTok, batching 20 stories into one call vs. 20 individual calls saves ~19 API round-trips and the fixed overhead per call. The prompt explicitly orders Claude to return entries in input order, making the zip-based merge safe.

**Why `max_tokens=8192`:**
At roughly 200–350 tokens per entry (headline + summary + significance), 25 stories requires ~8,750 tokens worst case. 8192 covers the typical case (10–20 stories per run). If `stop_reason == "max_tokens"`, the tool_input will be None and a `ValueError` is raised — the pipeline will surface this as a failed run. This is acceptable for MVP; a larger token limit or chunked batching is a Phase 2 enhancement.

**`_MAX_CHUNK_CHARS = 600`:**
Newsletter story segments are often 800–2000+ chars. 600 chars captures the headline and first 2–3 sentences — enough context for summarization without ballooning input tokens. The full text is preserved in `StoryGroup.chunks` for potential future use.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import ai; from ai.claude_client import generate_digest, _TOOL_SCHEMA, _TOOL_NAME, _build_user_message; print('all imports OK')"`
  Expected output or result:
  ```
  all imports OK
  ```

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ai.claude_client import _TOOL_SCHEMA, _TOOL_NAME; assert _TOOL_SCHEMA['name'] == _TOOL_NAME; schema = _TOOL_SCHEMA['input_schema']; assert schema['type'] == 'object'; assert 'entries' in schema['properties']; item = schema['properties']['entries']['items']; assert set(item['required']) == {'headline', 'summary', 'significance'}; assert 'sources' not in item['properties']; print('Tool schema check PASSED'); print('entry required fields:', item['required'])"`
  Expected output or result:
  ```
  Tool schema check PASSED
  entry required fields: ['headline', 'summary', 'significance']
  ```

- Item to check:
  Prompt builder and empty-input dry-run (Level 3 command)
  Expected output or result:
  ```
  Prompt builder check PASSED
  Prompt length (chars): <any positive integer>
  Empty input guard PASSED
  ```

- Item to check:
  `ai/__init__.py` exists
  Expected output or result:
  File present at `ai/__init__.py` (visible in Completed Tasks section of execution report)

- Item to check:
  `ai/claude_client.py` exists
  Expected output or result:
  File present at `ai/claude_client.py` (visible in Completed Tasks section of execution report)

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import inspect, asyncio; from ai.claude_client import generate_digest; print('async:', asyncio.iscoroutinefunction(generate_digest)); print('sig:', inspect.signature(generate_digest))"`
  Expected output or result:
  ```
  async: True
  sig: (story_groups: list[processing.deduplicator.StoryGroup], folder: str) -> list[dict]
  ```
