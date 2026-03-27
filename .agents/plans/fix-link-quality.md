# Feature: Fix link quality — boilerplate filtering + per-chunk link association

The following plan should be complete, but read both target files fully before implementing.

Pay special attention to: the anchor text matching approach (html2text with `ignore_links=True` preserves anchor text in body text — this is what makes per-chunk matching possible), the conservative boilerplate filter (must not drop real story CTAs like "Read more"), and the fact that only TWO files change.

## Feature Description

Fix two link quality bugs that cause digest entries to carry irrelevant, noisy source links:

1. **Boilerplate links in `email_parser.py`**: `_extract_links()` currently returns every non-mailto link — including unsubscribe, privacy policy, view-in-browser, social media, and footer links. These pollute every `ParsedEmail.links` list and propagate through to digest sources.

2. **Wrong chunk-to-link association in `embedder.py`**: `_segment_email()` assigns `parsed_email.links` (the full email link list) to every `StoryChunk` it produces. A chunk about "OpenAI releases GPT-5" ends up with all 30+ links from the entire newsletter.

## User Story

As the digest pipeline,
I want each story chunk to carry only the links that appear within its own text segment, and only after boilerplate links have been removed from the email,
So that digest source entries point to the actual story being summarized, not to unsubscribe pages, social profiles, or links from other stories.

## Problem Statement

User reports that even in successful runs, digest entries include:
- Unsubscribe, privacy policy, archive, "view online" links (boilerplate)
- Social media links (Twitter/LinkedIn/Facebook icons)
- Generic homepage links
- Links from completely unrelated stories in the same newsletter

Both root causes are in the link extraction and assignment pipeline.

## Scope

- In scope: `ingestion/email_parser.py` (boilerplate filter), `processing/embedder.py` (per-chunk link assignment)
- Out of scope: `deduplicator.py`, `claude_client.py`, `digest_builder.py` — no changes needed; they consume `chunk.links` as-is

## Solution Statement

**Fix 1 — `email_parser.py`**: Add a `_is_boilerplate_link(url, anchor_text) -> bool` predicate and call it in `_extract_links()` to filter links before they enter `ParsedEmail.links`. Filter on URL fragments (e.g., "unsubscribe") and exact anchor text (e.g., "Privacy Policy").

**Fix 2 — `embedder.py`**: Add a `_links_for_chunk(text, all_links) -> list[dict]` helper that returns only the links from `all_links` whose `anchor_text` appears (case-insensitive substring) in the chunk's plain text. Update `_segment_email()` to call this helper instead of assigning the full link list. This works because `html2text` with `ignore_links=True` strips `href` attributes but **preserves anchor text** in the body — so "Read more about GPT-5" remains in the plain text even though the URL is gone.

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`, `processing/embedder.py`
**Dependencies**: None new
**Assumptions**:
- `html2text` with `ignore_links=True` preserves anchor text inline in the body string (verified by design: it renders `<a href="url">text</a>` → `text`)
- Boilerplate filter should be conservative: do NOT filter "Read more", "Learn more", "Full story" — these are valid story CTAs
- A chunk with no matching anchor text links should have `links=[]` (no links is better than wrong links)

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 48–58) — `_extract_links()`: the function to update; currently returns all non-mailto links with non-empty anchor text with no filtering
- `ingestion/email_parser.py` (lines 14–27) — existing module-level constants pattern (`_NOISE_TAGS`, `_HIDDEN_STYLE_PATTERNS`, `_HIDDEN_CLASS_KEYWORDS`); new boilerplate constant sets follow the same pattern
- `processing/embedder.py` (lines 40–53) — `_segment_email()`: the function to update; line 50 `links=parsed_email.links` is the bug
- `processing/embedder.py` (lines 14–19) — existing module-level constants pattern; `_links_for_chunk` helper follows the same structure

### Patterns to Follow

**Module-level frozenset constants** (mirror `email_parser.py` lines 15–27):
```python
_BOILERPLATE_URL_FRAGMENTS = frozenset({
    "unsubscribe", "optout", "opt-out", "manage-subscription",
    "email-preference", "email-prefs", "email-settings",
})

_BOILERPLATE_ANCHORS = frozenset({
    "unsubscribe", "opt out", "opt-out",
    "manage preferences", "update preferences", "email preferences",
    "view online", "view in browser", "view as web page", "view this email",
    "read online", "read in browser",
    "privacy policy", "privacy notice",
    "terms of service", "terms of use", "terms & conditions",
    "contact us",
    "advertise", "advertise with us",
    "subscribe", "forward to a friend",
    "tweet this", "share on twitter", "share on facebook",
    "facebook", "twitter", "linkedin", "instagram", "youtube",
    "all rights reserved",
})
```

**Private helper function style** (mirror `_strip_noise` in `email_parser.py` and `_encoding_text` in `embedder.py`):
- Lowercase, underscore-prefixed name
- Short docstring
- No logging (pure transformation)

---

## IMPLEMENTATION PLAN

### Phase 1: Boilerplate filter in `email_parser.py`

Add two frozensets of boilerplate signals and a predicate function, then call it in `_extract_links()`.

### Phase 2: Per-chunk link association in `embedder.py`

Add `_links_for_chunk()` helper and update `_segment_email()` to call it.

---

## STEP-BY-STEP TASKS

### TASK 1 — UPDATE `ingestion/email_parser.py`

#### 1a — Add boilerplate constant sets after line 27 (after `_HIDDEN_CLASS_KEYWORDS`)

Insert immediately after line 27, before the blank line before `@dataclass`:

```python
_BOILERPLATE_URL_FRAGMENTS = frozenset({
    "unsubscribe", "optout", "opt-out", "manage-subscription",
    "email-preference", "email-prefs", "email-settings",
})

# Exact-match anchor texts (normalised to lowercase) that indicate footer/boilerplate links.
# Conservative: does NOT include "read more", "learn more", "full story" (legitimate CTAs).
_BOILERPLATE_ANCHORS = frozenset({
    "unsubscribe", "opt out", "opt-out",
    "manage preferences", "update preferences", "email preferences",
    "view online", "view in browser", "view as web page", "view this email",
    "read online", "read in browser",
    "privacy policy", "privacy notice",
    "terms of service", "terms of use", "terms & conditions",
    "contact us",
    "advertise", "advertise with us",
    "subscribe", "forward to a friend",
    "tweet this", "share on twitter", "share on facebook",
    "facebook", "twitter", "linkedin", "instagram", "youtube",
    "all rights reserved",
})
```

- **PATTERN**: Mirror `_HIDDEN_CLASS_KEYWORDS` at `email_parser.py` line 27 (module-level frozenset constant)
- **GOTCHA**: Use `frozenset` not `set` — frozensets are immutable and slightly faster for membership tests

#### 1b — Add `_is_boilerplate_link()` helper after the new constants

Insert after the new constant block, before `@dataclass ParsedEmail`:

```python
def _is_boilerplate_link(url: str, anchor_text: str) -> bool:
    """Return True if this link is a boilerplate footer/navigation link, not a story link."""
    url_lower = url.lower()
    anchor_lower = anchor_text.lower().strip()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    if anchor_lower in _BOILERPLATE_ANCHORS:
        return True
    return False
```

- **PATTERN**: Mirror `_strip_noise` style — private, no logging, returns a simple value
- **GOTCHA**: Check URL fragments with `in url_lower` (substring), not equality — URLs are full strings like `https://example.com/unsubscribe?id=123`

#### 1c — Update `_extract_links()` to call the filter (lines 48–58)

Change the function body to skip boilerplate links:

**Old** (lines 51–57):
```python
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        if not url or url.startswith("mailto:"):
            continue
        anchor_text = a.get_text(strip=True)
        if anchor_text:
            links.append({"url": url, "anchor_text": anchor_text})
```

**New**:
```python
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        if not url or url.startswith("mailto:"):
            continue
        anchor_text = a.get_text(strip=True)
        if anchor_text and not _is_boilerplate_link(url, anchor_text):
            links.append({"url": url, "anchor_text": anchor_text})
```

- **IMPLEMENT**: Add `and not _is_boilerplate_link(url, anchor_text)` condition
- **GOTCHA**: Only one line changes in the loop — do not restructure the function
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.email_parser import _is_boilerplate_link, _extract_links; print('import OK')"`

---

### TASK 2 — UPDATE `processing/embedder.py`

#### 2a — Add `_links_for_chunk()` helper after `_encoding_text` (after line 58)

Insert after `_encoding_text()` function, before `embed_and_cluster()`:

```python
def _links_for_chunk(text: str, all_links: list[dict]) -> list[dict]:
    """Return the subset of links whose anchor text appears in this chunk's text.

    html2text with ignore_links=True strips href attributes but keeps anchor text
    inline, so anchor text matching reliably associates links with their story chunk.
    """
    text_lower = text.lower()
    return [
        link for link in all_links
        if link.get("anchor_text", "").lower() in text_lower
        and link.get("anchor_text", "")  # skip links with empty anchor text
    ]
```

- **PATTERN**: Mirror `_encoding_text()` style at `embedder.py` lines 56–58
- **GOTCHA**: The condition `anchor_text.lower() in text_lower` does a substring search — anchor text "Read more about GPT-5" matches if those exact words appear in the chunk text. This is intentional.
- **GOTCHA**: Guard `and link.get("anchor_text", "")` to skip any links that somehow slipped through with empty anchor text (defensive programming)

#### 2b — Update `_segment_email()` line 50: replace `links=parsed_email.links` with per-chunk call

**Old** (lines 47–51):
```python
            chunks.append(StoryChunk(
                text=seg,
                sender=parsed_email.sender,
                links=parsed_email.links,
            ))
```

**New**:
```python
            chunks.append(StoryChunk(
                text=seg,
                sender=parsed_email.sender,
                links=_links_for_chunk(seg, parsed_email.links),
            ))
```

- **IMPLEMENT**: Replace `links=parsed_email.links` with `links=_links_for_chunk(seg, parsed_email.links)`
- **GOTCHA**: `seg` is already stripped (line 45 `seg = seg.strip()`) — pass it directly; no need to strip again
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.embedder import _links_for_chunk; print('import OK')"`

---

## TESTING STRATEGY

No separate test file. Validation uses inline synthetic fixtures.

### Edge Cases

- Anchor text that appears in multiple chunks → each of those chunks gets that link (acceptable; rare for story-specific CTAs)
- Chunk with no matching anchor text → `links=[]` (correct — no links is better than wrong links)
- Boilerplate URL ("https://example.com/unsubscribe?token=abc") → filtered regardless of anchor text
- Boilerplate anchor "Privacy Policy" → filtered regardless of URL
- Legitimate "Read more" anchor → NOT filtered (not in `_BOILERPLATE_ANCHORS`)
- Empty links list on `ParsedEmail` → `_links_for_chunk` returns `[]` correctly

---

## VALIDATION COMMANDS

### Level 1: Import checks for both modified files

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import _is_boilerplate_link, _extract_links, _BOILERPLATE_ANCHORS, _BOILERPLATE_URL_FRAGMENTS
from processing.embedder import _links_for_chunk, _segment_email
print('all imports OK')
print('boilerplate anchor count:', len(_BOILERPLATE_ANCHORS))
print('boilerplate url fragment count:', len(_BOILERPLATE_URL_FRAGMENTS))
"
```
Expected output:
```
all imports OK
boilerplate anchor count: <number between 20 and 35>
boilerplate url fragment count: 7
```

### Level 2: Boilerplate filter unit tests

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import _is_boilerplate_link

# Should be filtered (boilerplate)
assert _is_boilerplate_link('https://example.com/unsubscribe?id=123', 'Unsubscribe'), 'unsubscribe URL failed'
assert _is_boilerplate_link('https://example.com/email-prefs', 'Manage preferences'), 'email-prefs URL failed'
assert _is_boilerplate_link('https://example.com/story', 'Privacy Policy'), 'privacy anchor failed'
assert _is_boilerplate_link('https://example.com/story', 'View online'), 'view online failed'
assert _is_boilerplate_link('https://example.com/story', 'Facebook'), 'facebook anchor failed'
assert _is_boilerplate_link('https://example.com/story', 'Contact us'), 'contact us failed'
assert _is_boilerplate_link('https://example.com/story', 'Subscribe'), 'subscribe failed'
print('Boilerplate filter PASSED (all boilerplate correctly detected)')

# Should NOT be filtered (legitimate story links)
assert not _is_boilerplate_link('https://openai.com/gpt5', 'Read more about GPT-5'), 'read more wrongly filtered'
assert not _is_boilerplate_link('https://openai.com/gpt5', 'OpenAI launches GPT-5'), 'headline wrongly filtered'
assert not _is_boilerplate_link('https://openai.com/gpt5', 'Learn more'), 'learn more wrongly filtered'
assert not _is_boilerplate_link('https://techcrunch.com/story', 'Full story'), 'full story wrongly filtered'
assert not _is_boilerplate_link('https://techcrunch.com/story', 'Read the announcement'), 'read announcement wrongly filtered'
print('Boilerplate filter PASSED (all legitimate links correctly kept)')
"
```
Expected output:
```
Boilerplate filter PASSED (all boilerplate correctly detected)
Boilerplate filter PASSED (all legitimate links correctly kept)
```

### Level 3: Per-chunk link association unit tests

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import _links_for_chunk

all_links = [
    {'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more about GPT-5'},
    {'url': 'https://anthropic.com/claude', 'anchor_text': 'Learn more about Claude'},
    {'url': 'https://example.com/home', 'anchor_text': 'Visit our website'},
]

# Chunk 1: contains the GPT-5 anchor
chunk1 = 'OpenAI launched GPT-5 today with improved reasoning. Read more about GPT-5'
result1 = _links_for_chunk(chunk1, all_links)
assert len(result1) == 1, f'Expected 1 link, got {len(result1)}: {result1}'
assert result1[0]['url'] == 'https://openai.com/gpt5'
print('Chunk 1 link match PASSED:', result1[0]['url'])

# Chunk 2: contains the Claude anchor
chunk2 = 'Anthropic released Claude 4. Learn more about Claude in their announcement.'
result2 = _links_for_chunk(chunk2, all_links)
assert len(result2) == 1, f'Expected 1 link, got {len(result2)}: {result2}'
assert result2[0]['url'] == 'https://anthropic.com/claude'
print('Chunk 2 link match PASSED:', result2[0]['url'])

# Chunk 3: no matching anchor text — should get no links
chunk3 = 'Regulators propose new AI safety framework in Brussels.'
result3 = _links_for_chunk(chunk3, all_links)
assert len(result3) == 0, f'Expected 0 links, got {len(result3)}: {result3}'
print('Chunk 3 no-match PASSED: links=[]')

# Empty links list
result4 = _links_for_chunk('Some text', [])
assert result4 == []
print('Empty links guard PASSED')
"
```
Expected output:
```
Chunk 1 link match PASSED: https://openai.com/gpt5
Chunk 2 link match PASSED: https://anthropic.com/claude
Chunk 3 no-match PASSED: links=[]
Empty links guard PASSED
```

### Level 4: End-to-end `_segment_email` integration test

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import ParsedEmail
from processing.embedder import _segment_email
from datetime import datetime

email = ParsedEmail(
    subject='AI Newsletter',
    sender='TLDR AI',
    date=datetime.now(),
    body='OpenAI launches GPT-5 with new reasoning capabilities. Read the announcement\n\nAnthropic unveils Claude 4 with extended context window. Learn more about Claude here\n\nUnsubscribe from this list',
    links=[
        {'url': 'https://openai.com/gpt5', 'anchor_text': 'Read the announcement'},
        {'url': 'https://anthropic.com/claude4', 'anchor_text': 'Learn more about Claude here'},
        {'url': 'https://newsletter.com/unsubscribe', 'anchor_text': 'Unsubscribe from this list'},
    ],
)

chunks = _segment_email(email)
print(f'Total chunks: {len(chunks)}')
for i, chunk in enumerate(chunks):
    print(f'  Chunk {i+1} links: {[l[\"url\"] for l in chunk.links]}')

# Verify chunk 1 has only the GPT-5 link
gpt_chunk = next((c for c in chunks if 'GPT-5' in c.text), None)
assert gpt_chunk is not None
assert len(gpt_chunk.links) == 1
assert gpt_chunk.links[0]['url'] == 'https://openai.com/gpt5'

# Verify chunk 2 has only the Claude link
claude_chunk = next((c for c in chunks if 'Claude' in c.text), None)
assert claude_chunk is not None
assert len(claude_chunk.links) == 1
assert claude_chunk.links[0]['url'] == 'https://anthropic.com/claude4'

# Verify no chunk has the unsubscribe link
all_urls = [l['url'] for c in chunks for l in c.links]
assert 'https://newsletter.com/unsubscribe' not in all_urls, 'Unsubscribe link leaked through!'

print('End-to-end _segment_email test PASSED')
"
```
Expected output:
```
Total chunks: <2 or 3 depending on segmentation>
  Chunk 1 links: ['https://openai.com/gpt5']
  Chunk 2 links: ['https://anthropic.com/claude4']
  <optional Chunk 3 lines>
End-to-end _segment_email test PASSED
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_is_boilerplate_link` exists in `email_parser.py` and is importable
- [ ] `_BOILERPLATE_URL_FRAGMENTS` and `_BOILERPLATE_ANCHORS` are module-level frozensets in `email_parser.py`
- [ ] `_links_for_chunk` exists in `embedder.py` and is importable
- [ ] `_segment_email` no longer uses `links=parsed_email.links` directly — calls `_links_for_chunk` instead
- [ ] Boilerplate filter detects URL fragments (unsubscribe) and anchor text matches (Privacy Policy)
- [ ] Legitimate CTAs ("Read more about...", "Learn more") are NOT filtered
- [ ] Chunk with no matching anchors gets `links=[]`
- [ ] Unsubscribe link never appears in any chunk's links

## ROLLBACK CONSIDERATIONS

- Two files modified; rollback = revert both with git
- No schema changes, no new files, no new dependencies

## ACCEPTANCE CRITERIA

- [ ] `_is_boilerplate_link("https://x.com/unsubscribe", "x")` returns `True`
- [ ] `_is_boilerplate_link("https://x.com/story", "Privacy Policy")` returns `True`
- [ ] `_is_boilerplate_link("https://openai.com/gpt5", "Read more about GPT-5")` returns `False`
- [ ] `_links_for_chunk("text containing Read more about GPT-5", all_links)` returns only the GPT-5 link
- [ ] `_links_for_chunk("text with no matching anchors", all_links)` returns `[]`
- [ ] All 4 validation commands pass
- [ ] No regressions in embedder import or deduplicator flow

---

## COMPLETION CHECKLIST

- [ ] Task 1a: `_BOILERPLATE_URL_FRAGMENTS` and `_BOILERPLATE_ANCHORS` added to `email_parser.py`
- [ ] Task 1b: `_is_boilerplate_link()` added to `email_parser.py`
- [ ] Task 1c: `_extract_links()` updated to call filter
- [ ] Task 2a: `_links_for_chunk()` added to `embedder.py`
- [ ] Task 2b: `_segment_email()` updated to call `_links_for_chunk`
- [ ] Level 1 passed
- [ ] Level 2 passed
- [ ] Level 3 passed
- [ ] Level 4 passed

---

## NOTES

**Why anchor text matching works:**
`html2text` with `ignore_links=True` renders `<a href="url">anchor text</a>` as just `anchor text` in the plain text output. So "Read more about GPT-5" appears literally in the chunk text. The `lower() in lower()` substring check reliably identifies which links belong to which chunk without requiring HTML re-parsing.

**Why "read more" / "learn more" are NOT in `_BOILERPLATE_ANCHORS`:**
These are the most common story CTAs in newsletters. "Read more" with a URL pointing to an article IS the story source link — exactly what we want in the digest. Filtering them would remove the most valuable links. The per-chunk association step limits them correctly: only the "Read more" that appears in a specific chunk's text is assigned to that chunk.

**Why not filter "short generic anchors" globally:**
"Here", "this", "click" are context-dependent. A link anchored "here" inside a story chunk is more useful than no link at all. The boilerplate filter focuses on clear-signal cases (known footer phrases, social platform names, legal text) where there is no ambiguity.

**Why per-chunk association instead of structural HTML parsing:**
Structural HTML parsing would require carrying the HTML tree through the pipeline alongside the plain text body, which is a larger architectural change. Anchor text matching achieves 90%+ of the benefit with a 5-line helper function.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.email_parser import _is_boilerplate_link, _extract_links, _BOILERPLATE_ANCHORS, _BOILERPLATE_URL_FRAGMENTS; from processing.embedder import _links_for_chunk, _segment_email; print('all imports OK'); print('boilerplate anchor count:', len(_BOILERPLATE_ANCHORS)); print('boilerplate url fragment count:', len(_BOILERPLATE_URL_FRAGMENTS))"`
  Expected output or result:
  ```
  all imports OK
  boilerplate anchor count: <number between 20 and 35>
  boilerplate url fragment count: 7
  ```

- Item to check:
  Boilerplate filter tests (Level 2 command)
  Expected output or result:
  ```
  Boilerplate filter PASSED (all boilerplate correctly detected)
  Boilerplate filter PASSED (all legitimate links correctly kept)
  ```

- Item to check:
  Per-chunk link association tests (Level 3 command)
  Expected output or result:
  ```
  Chunk 1 link match PASSED: https://openai.com/gpt5
  Chunk 2 link match PASSED: https://anthropic.com/claude4
  Chunk 3 no-match PASSED: links=[]
  Empty links guard PASSED
  ```

- Item to check:
  End-to-end `_segment_email` integration test (Level 4 command)
  Expected output or result:
  ```
  Total chunks: <any positive integer>
  <one or more "Chunk N links:" lines>
  End-to-end _segment_email test PASSED
  ```
