# Feature: Fix link quality (round 2) — generic CTA filtering, empty source removal, sponsor chunk drop

The following plan should be complete, but read all three target files in full before implementing.

Pay special attention to: removing `seen_empty_senders` entirely from `_build_sources` (not just the else block), keeping existing boilerplate entries in `_BOILERPLATE_ANCHORS` when adding new ones, and making `_BOILERPLATE_SEGMENT_SIGNALS` conservative (only fire on clear sponsor language, not general text).

## Feature Description

Three follow-up fixes to the link quality issues from the previous round:

1. **`email_parser.py` — expand `_BOILERPLATE_ANCHORS`**: The previous filter blocked known footer phrases but left through generic CTAs ("read more", "learn more", "here") and common navigation/sponsor anchor texts. Since these anchors appear many times per newsletter, the previous round's anchor-text matching assigned them to every chunk that happened to contain the word "more" — producing irrelevant multi-link source lists. Adding them to the boilerplate set drops them from extraction entirely, which is cleaner than trying to assign them correctly.

2. **`deduplicator.py` — remove empty-URL source entries**: `_build_sources()` currently adds `{"newsletter": sender, "url": "", "anchor_text": ""}` for every chunk that has no links. The user reports these empty entries as noise in the output. With the stricter boilerplate filter, more chunks will have `links=[]` legitimately. Empty source entries with no URL add no value to the digest; they should be dropped entirely.

3. **`embedder.py` — drop sponsor/shell chunks**: Newsletter sponsor blocks (e.g., "Brought to you by Acme. Try Acme today…") pass the current `_MIN_CHUNK_CHARS = 50` threshold and become embedded story candidates. A targeted signal-based filter removes them before embedding.

## User Story

As the digest pipeline,
I want source entries to contain only specific, URL-bearing story links, and story chunk candidates to contain only actual news content,
So that digest entries show clean, relevant sources and sponsor blocks never appear as digest entries.

## Scope

- In scope: `ingestion/email_parser.py` (boilerplate anchor expansion), `processing/deduplicator.py` (drop empty-URL source entries), `processing/embedder.py` (sponsor chunk filter)
- Out of scope: `claude_client.py`, `digest_builder.py`, any API or frontend changes

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `email_parser.py`, `deduplicator.py`, `embedder.py`
**Dependencies**: None new

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 29–49) — current `_BOILERPLATE_URL_FRAGMENTS` and `_BOILERPLATE_ANCHORS`; new entries are additive only, existing entries stay
- `ingestion/email_parser.py` (line 35) — comment "Conservative: does NOT include 'read more', 'learn more'…" — **must be removed** since those are now added
- `processing/deduplicator.py` (lines 20–44) — full `_build_sources()`; remove `seen_empty_senders` (line 22) and the entire `else` block (lines 35–43)
- `processing/embedder.py` (lines 14–19) — module-level constants; new constants follow this pattern
- `processing/embedder.py` (lines 40–53) — `_segment_email()`; the `if len(seg) >= _MIN_CHUNK_CHARS:` guard gets an additional `and not _is_boilerplate_segment(seg)` condition

---

## STEP-BY-STEP TASKS

### TASK 1 — UPDATE `ingestion/email_parser.py`

#### 1a — Replace `_BOILERPLATE_ANCHORS` with expanded set and remove outdated comment

Replace the existing `_BOILERPLATE_ANCHORS` frozenset (lines 34–49, including the comment above it) with:

```python
# Exact-match anchor texts (normalised to lowercase) that indicate non-story links.
# Includes generic CTAs that are too ambiguous to assign to a specific story chunk.
_BOILERPLATE_ANCHORS = frozenset({
    # Unsubscribe / preferences
    "unsubscribe", "opt out", "opt-out",
    "manage preferences", "update preferences", "email preferences",
    # View / browser
    "view online", "view in browser", "view as web page", "view this email",
    "read online", "read in browser",
    # Legal / policy
    "privacy policy", "privacy notice",
    "terms of service", "terms of use", "terms & conditions",
    "all rights reserved",
    # Contact / admin
    "contact us", "forward to a friend",
    # Advertising
    "advertise", "advertise with us",
    "sponsored", "sponsor", "advertisement", "ad", "advertorial",
    "presented by", "powered by", "brought to you by",
    # Social platforms (icon links)
    "facebook", "twitter", "linkedin", "instagram", "youtube",
    "tweet this", "share on twitter", "share on facebook",
    "share", "tweet", "retweet", "pin", "pin it",
    # Navigation
    "subscribe", "home", "about", "archive", "archives", "blog", "newsletter",
    "back", "back to top", "next", "previous",
    # Generic CTAs — too ambiguous to assign to a specific story
    "read more", "learn more", "click here", "here", "more", "see more",
    "find out more", "get started", "sign up", "try now", "try for free",
    "try it free", "try it now", "buy now", "shop now", "download now",
})
```

- **GOTCHA**: Keep the existing entries — only the comment line and the frozenset definition change. The URL fragments constant (`_BOILERPLATE_URL_FRAGMENTS`) is unchanged.
- **GOTCHA**: Remove the old comment that said "Conservative: does NOT include 'read more', 'learn more', 'full story'" — it's no longer accurate.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.email_parser import _BOILERPLATE_ANCHORS, _is_boilerplate_link; print(len(_BOILERPLATE_ANCHORS), 'anchors'); assert _is_boilerplate_link('https://x.com', 'read more'); assert _is_boilerplate_link('https://x.com', 'sponsored'); assert not _is_boilerplate_link('https://openai.com/gpt5', 'OpenAI Releases GPT-5'); print('anchor expansion OK')"`

---

### TASK 2 — UPDATE `processing/deduplicator.py`

#### 2a — Remove `seen_empty_senders` and the empty-URL `else` block from `_build_sources()`

Replace the full body of `_build_sources()` with a version that only adds source entries for chunks that have actual URLs:

**Old** (lines 18–45 of current file):
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

**New**:
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

- **IMPLEMENT**: Remove `seen_empty_senders` variable, remove `if chunk.links:` branch wrapper, remove `else` block entirely
- **GOTCHA**: The inner `for link in chunk.links:` loop is now the direct body of the `for chunk` loop. If `chunk.links` is empty, iterating over it produces nothing — no special guard needed.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.embedder import StoryChunk; from processing.deduplicator import _build_sources; c = StoryChunk(text='x', sender='N', links=[]); result = _build_sources([c]); assert result == [], f'Expected [], got {result}'; print('empty-URL removal OK')"`

---

### TASK 3 — UPDATE `processing/embedder.py`

#### 3a — Add `_BOILERPLATE_SEGMENT_SIGNALS` constant after `_SPLIT_PATTERN` (after line 19)

Insert after line 19 (`_SPLIT_PATTERN = ...`):

```python
# Substrings that identify sponsor or shell segments — checked against lowercase chunk text.
# Conservative: only fire on unambiguous sponsor/advertorial language.
_BOILERPLATE_SEGMENT_SIGNALS = (
    "sponsored by",
    "brought to you by",
    "presented by",
    "this newsletter is supported by",
    "this issue is sponsored",
    "our sponsor",
    "a word from our sponsor",
    "advertisement",
    "advertorial",
)
```

- **PATTERN**: Mirror `_SPLIT_PATTERN` and `_MIN_CHUNK_CHARS` module-level constant style

#### 3b — Add `_is_boilerplate_segment()` helper after `_get_model()` (insert before `_segment_email`)

Insert before `_segment_email()`:

```python
def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

#### 3c — Update `_segment_email()` condition to call the filter

**Old** (line 46):
```python
        if len(seg) >= _MIN_CHUNK_CHARS:
```

**New**:
```python
        if len(seg) >= _MIN_CHUNK_CHARS and not _is_boilerplate_segment(seg):
```

- **GOTCHA**: Only one token changes — add `and not _is_boilerplate_segment(seg)` to the existing condition. Do not restructure the function.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.embedder import _is_boilerplate_segment; assert _is_boilerplate_segment('Sponsored by Acme Corp. Try Acme today.'); assert _is_boilerplate_segment('This newsletter is supported by our partners.'); assert not _is_boilerplate_segment('OpenAI launches GPT-5 with new reasoning capabilities.'); print('segment filter OK')"`

---

## VALIDATION COMMANDS

### Level 1: All imports

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import _BOILERPLATE_ANCHORS, _is_boilerplate_link
from processing.deduplicator import _build_sources
from processing.embedder import _is_boilerplate_segment, _segment_email
print('all imports OK')
print('anchor count:', len(_BOILERPLATE_ANCHORS))
"
```
Expected output:
```
all imports OK
anchor count: <number >= 40>
```

### Level 2: Expanded anchor filter

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.email_parser import _is_boilerplate_link

# New additions — must be filtered
assert _is_boilerplate_link('https://x.com/story', 'Read more'), 'read more not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Learn more'), 'learn more not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Click here'), 'click here not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Here'), 'here not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Sponsored'), 'sponsored not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Presented by'), 'presented by not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Home'), 'home not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Get started'), 'get started not filtered'
assert _is_boilerplate_link('https://x.com/story', 'Sign up'), 'sign up not filtered'
print('New boilerplate anchors PASSED')

# Existing entries — must still be filtered
assert _is_boilerplate_link('https://x.com/unsub', 'Unsubscribe')
assert _is_boilerplate_link('https://x.com/story', 'Privacy Policy')
assert _is_boilerplate_link('https://x.com/story', 'Facebook')
print('Existing boilerplate anchors still PASSED')

# Legitimate story links — must NOT be filtered
assert not _is_boilerplate_link('https://openai.com/gpt5', 'OpenAI launches GPT-5')
assert not _is_boilerplate_link('https://openai.com/gpt5', 'Read the full announcement')
assert not _is_boilerplate_link('https://techcrunch.com/story', 'Full story')
assert not _is_boilerplate_link('https://techcrunch.com/story', 'See the research paper')
print('Legitimate links still pass PASSED')
"
```
Expected output:
```
New boilerplate anchors PASSED
Existing boilerplate anchors still PASSED
Legitimate links still pass PASSED
```

### Level 3: Empty-URL source removal

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import StoryChunk
from processing.deduplicator import _build_sources

# Chunk with no links — must produce no source entries
no_link_chunk = StoryChunk(text='Story text.', sender='Newsletter A', links=[])
result = _build_sources([no_link_chunk])
assert result == [], f'Expected [], got {result}'
print('Empty-URL removal PASSED: no-link chunk produces no sources')

# Chunk with a real link — must still produce a source entry
link_chunk = StoryChunk(
    text='Story text.',
    sender='Newsletter B',
    links=[{'url': 'https://example.com/story', 'anchor_text': 'Full details here'}],
)
result2 = _build_sources([link_chunk])
assert len(result2) == 1
assert result2[0]['url'] == 'https://example.com/story'
assert result2[0]['newsletter'] == 'Newsletter B'
print('Real link source entry PASSED:', result2[0]['url'])

# Mixed cluster: no-link + link chunk — only the linked chunk contributes a source
result3 = _build_sources([no_link_chunk, link_chunk])
assert len(result3) == 1, f'Expected 1 source, got {len(result3)}: {result3}'
assert all(s['url'] != '' for s in result3)
print('Mixed cluster PASSED: only URL-bearing sources included')
"
```
Expected output:
```
Empty-URL removal PASSED: no-link chunk produces no sources
Real link source entry PASSED: https://example.com/story
Mixed cluster PASSED: only URL-bearing sources included
```

### Level 4: Sponsor segment filter

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from processing.embedder import _is_boilerplate_segment, _segment_email
from ingestion.email_parser import ParsedEmail
from datetime import datetime

# Signal detection
assert _is_boilerplate_segment('Sponsored by Acme Corp. Try Acme today and save 20%.')
assert _is_boilerplate_segment('Brought to you by Example Inc — the fastest way to ship code.')
assert _is_boilerplate_segment('This newsletter is supported by our partners at CloudCo.')
assert _is_boilerplate_segment('A word from our sponsor: Startup tools for developers.')
assert not _is_boilerplate_segment('OpenAI launches GPT-5 with improved reasoning and vision capabilities.')
assert not _is_boilerplate_segment('Anthropic raised \$2.5 billion in new funding this week.')
print('Segment signal detection PASSED')

# Sponsor chunk must be dropped from _segment_email output
parsed = ParsedEmail(
    subject='AI Newsletter',
    sender='TLDR AI',
    date=datetime.now(),
    body='OpenAI launches GPT-5 with improved reasoning capabilities.\n\nSponsored by Acme Corp. Get 20% off your first month with code TLDR.\n\nAnthropic raises more funding to expand Claude capabilities.',
    links=[],
)
chunks = _segment_email(parsed)
texts = [c.text for c in chunks]
print(f'Chunks produced: {len(chunks)}')
for t in texts:
    print(' -', t[:60])
assert not any('Sponsored by' in t for t in texts), 'Sponsor chunk leaked into chunks!'
assert any('GPT-5' in t for t in texts), 'Real story dropped!'
assert any('Anthropic' in t for t in texts), 'Real story dropped!'
print('Sponsor chunk drop PASSED')
"
```
Expected output:
```
Segment signal detection PASSED
Chunks produced: 2
 - OpenAI launches GPT-5 with improved reasoning capabilities.
 - Anthropic raises more funding to expand Claude capabilities.
Sponsor chunk drop PASSED
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_BOILERPLATE_ANCHORS` contains "read more", "learn more", "click here", "sponsored", "presented by", "home"
- [ ] Old comment about "conservative: does NOT include read more" is removed
- [ ] `_build_sources()` no longer contains `seen_empty_senders` variable or `else` block
- [ ] `_build_sources([chunk_with_no_links])` returns `[]`
- [ ] `_is_boilerplate_segment` exists and is importable from `processing.embedder`
- [ ] Sponsor blocks do not appear as story chunks in `_segment_email` output
- [ ] All 4 validation commands pass

## ROLLBACK CONSIDERATIONS

- Three files modified; rollback = revert all three with git
- No schema changes, no new files, no new dependencies

## ACCEPTANCE CRITERIA

- [ ] `_is_boilerplate_link("https://x.com", "Read more")` returns `True`
- [ ] `_is_boilerplate_link("https://x.com", "Sponsored")` returns `True`
- [ ] `_is_boilerplate_link("https://openai.com/gpt5", "OpenAI launches GPT-5")` returns `False`
- [ ] `_build_sources([chunk_with_links=[]])` returns `[]` (no empty URL entries)
- [ ] `_is_boilerplate_segment("Sponsored by Acme…")` returns `True`
- [ ] Sponsor chunks excluded from `_segment_email` output
- [ ] All 4 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1: `_BOILERPLATE_ANCHORS` expanded, old comment removed
- [ ] Task 2: `_build_sources()` simplified — no `seen_empty_senders`, no `else` block
- [ ] Task 3a: `_BOILERPLATE_SEGMENT_SIGNALS` added to `embedder.py`
- [ ] Task 3b: `_is_boilerplate_segment()` added to `embedder.py`
- [ ] Task 3c: `_segment_email()` condition updated
- [ ] Level 1 passed
- [ ] Level 2 passed
- [ ] Level 3 passed
- [ ] Level 4 passed

---

## NOTES

**Why "read more" / "learn more" are now in `_BOILERPLATE_ANCHORS`:**
The previous plan's anchor-text matching assigned ALL "Read more" links from an email to every chunk containing those words. This produced multi-link source lists where every story from a newsletter appeared to link to every other story. Dropping "read more" links entirely is cleaner: stories may have `sources=[]` but will not have wrong sources.

**Why removing empty-URL sources is correct:**
An empty-URL source entry `{"newsletter": "TLDR AI", "url": "", "anchor_text": ""}` has no value for the reader — there's nothing to click. The newsletter name still appears in the AI-generated entry's `sources` only if the newsletter had a specific, URL-bearing link for that story. This raises the bar: sources must be clickable.

**Why `_BOILERPLATE_SEGMENT_SIGNALS` is conservative:**
Only exact-phrase patterns that unambiguously signal sponsor/ad content are included. "Sponsored by" will not appear in a legitimate news story. False positives would drop real stories — so erring towards under-filtering is deliberate here.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.email_parser import _BOILERPLATE_ANCHORS, _is_boilerplate_link; from processing.deduplicator import _build_sources; from processing.embedder import _is_boilerplate_segment, _segment_email; print('all imports OK'); print('anchor count:', len(_BOILERPLATE_ANCHORS))"`
  Expected output or result:
  ```
  all imports OK
  anchor count: <number >= 40>
  ```

- Item to check:
  Expanded anchor filter tests (Level 2 command)
  Expected output or result:
  ```
  New boilerplate anchors PASSED
  Existing boilerplate anchors still PASSED
  Legitimate links still pass PASSED
  ```

- Item to check:
  Empty-URL source removal tests (Level 3 command)
  Expected output or result:
  ```
  Empty-URL removal PASSED: no-link chunk produces no sources
  Real link source entry PASSED: https://example.com/story
  Mixed cluster PASSED: only URL-bearing sources included
  ```

- Item to check:
  Sponsor segment filter tests (Level 4 command)
  Expected output or result:
  ```
  Segment signal detection PASSED
  Chunks produced: 2
   - OpenAI launches GPT-5 with improved reasoning capabilities.
   - Anthropic raises more funding to expand Claude capabilities.
  Sponsor chunk drop PASSED
  ```
