# Feature: story-link-association — URL-Only Link Filtering in Sections, Remove Dead Global Link Extraction

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to the exact call site in `_extract_sections()` (line 246) and the two `_extract_links()` call sites in `parse_emails()` (lines 361, 370). Read the full current file before editing.

## Feature Description

Two related problems in `ingestion/email_parser.py`:

**Problem 1 — Anchor-text filtering drops inline story links.**
In `_extract_sections()`, every inline link is tested with `_is_boilerplate_link(url, anchor)`, which filters links whose anchor text appears in `_BOILERPLATE_ANCHORS`. This includes `"read more"`, `"learn more"`, `"here"`, `"click here"`, `"more"`, `"find out more"`, and ~50 other generic phrases. These are frequently the *only* story link in a newsletter section (e.g., `[Read the full paper here](https://arxiv.org/abs/1234)`). Within a section that has already passed the content filters (`_MIN_SECTION_CHARS` + `_is_boilerplate_segment()`), anchor text quality is not a reliable signal — any link is in the context of real content.

**Problem 2 — Dead global link extraction code.**
`parse_emails()` calls `_extract_links()` in both the plain+html branch (line 361) and the html-only branch (line 370) to populate `ParsedEmail.links`. However, `_segment_email()` in `embedder.py` never reads `parsed_email.links` when sections are present — it uses `section["links"]` directly (embedder.py line 53). `ParsedEmail.links` is computed but never consumed. This is dead code that implies a global re-association step that does not actually happen.

## User Story

As the pipeline,
I want inline story links to be preserved regardless of their anchor text, and link extraction to flow exclusively through section-level association,
So that source attribution is accurate and the data flow is explicit and correct.

## Problem Statement

`_is_boilerplate_link(url, anchor)` applies anchor-text-based filtering within `_extract_sections()`. This was designed to exclude navigation icon-links (Twitter, Facebook) and generic CTAs, but it also drops legitimate inline article links whose anchor text happens to be generic ("read more", "here", "learn more"). The result: story sections have fewer links than they should, making them more likely to be dropped as sourceless by the deduplicator.

The global `_extract_links()` calls are dead code — the resulting `ParsedEmail.links` list is never used when sections are available (the normal path for HTML emails).

## Scope

- In scope: `ingestion/email_parser.py` — add `_SOCIAL_DOMAINS`, add `_is_boilerplate_url()`, update link filter call in `_extract_sections()`, remove dead `_extract_links()` calls from `parse_emails()`, remove `_extract_links()` function
- Out of scope: `_BOILERPLATE_ANCHORS`, `_BOILERPLATE_ANCHOR_SUBSTRINGS`, `_is_boilerplate_link()` — keep unchanged (still used conceptually, may be useful later, do not delete), `_BOILERPLATE_SEGMENT_SIGNALS`, `_MIN_SECTION_CHARS` (Loop 1 — do not touch), `_normalize_url()`, `_TRACKING_PARAMS` (Loop 2 — do not touch), `embedder.py`, `deduplicator.py`, `claude_client.py`

## Solution Statement

1. Add `_SOCIAL_DOMAINS` frozenset — social platform base domains (twitter, facebook, etc.) that are structural sharing links, not story destinations.

2. Add `_is_boilerplate_url(url: str) -> bool` — URL-only boilerplate check. Uses `_BOILERPLATE_URL_FRAGMENTS` (existing email management paths) plus a domain check against `_SOCIAL_DOMAINS`. No anchor text check.

3. In `_extract_sections()`, replace `if _is_boilerplate_link(url, anchor):` with `if _is_boilerplate_url(url):`. Links with generic anchor text that point to real content URLs (arxiv.org, blog posts, company sites) are now preserved.

4. In `parse_emails()`:
   - Remove `html_soup = BeautifulSoup(html_text, "lxml")` + `links = _extract_links(html_soup)` from the plain+html branch — these were only there to populate `ParsedEmail.links`
   - Remove `links = _extract_links(soup)` from the html-only branch
   - Remove `links: list[dict] = []` initialization (no longer needed)
   - Pass `links=[]` explicitly to `ParsedEmail()` constructor (self-documenting that global links are intentionally empty)

5. Remove `_extract_links()` function definition — it has no callers after step 4.

6. Update `ParsedEmail.links` field comment to reflect it is intentionally empty (all links are now section-local).

## Feature Metadata

**Feature Type**: Bug Fix + Refactor
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`
**Dependencies**: None — `urlparse` already imported (Loop 2)
**Assumptions**: Within a section that has passed `_MIN_SECTION_CHARS = 100` and `_is_boilerplate_segment()`, URL-based filtering alone is sufficient to exclude navigation links. Social sharing links are identified by domain, not anchor text.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 31–34) — `_BOILERPLATE_URL_FRAGMENTS` frozenset. `_SOCIAL_DOMAINS` follows the same frozenset pattern and is placed after `_TRACKING_PARAMS`.
- `ingestion/email_parser.py` (lines 86–96) — `_TRACKING_PARAMS` frozenset. Add `_SOCIAL_DOMAINS` immediately after this block.
- `ingestion/email_parser.py` (lines 126–168) — `_normalize_url()` and `_is_boilerplate_link()`. Add `_is_boilerplate_url()` between them (after `_normalize_url()`, before `_is_boilerplate_link()`).
- `ingestion/email_parser.py` (lines 241–253) — link extraction loop inside `_extract_sections()`. **The single line change**: `_is_boilerplate_link(url, anchor)` → `_is_boilerplate_url(url)`.
- `ingestion/email_parser.py` (lines 277–287) — `_extract_links()` function. **Remove entirely.**
- `ingestion/email_parser.py` (lines 319–403) — `parse_emails()`. Remove two `_extract_links()` call blocks. Remove `links: list[dict] = []`. Update `ParsedEmail()` constructor.
- `processing/embedder.py` (lines 48–62) — `_segment_email()`. **Read to confirm** it uses `section["links"]` not `parsed_email.links`. No changes needed here.

### New Files to Create

None. All changes in `ingestion/email_parser.py`.

### Patterns to Follow

**frozenset constant pattern** (email_parser.py line 31):
```python
_BOILERPLATE_URL_FRAGMENTS = frozenset({
    "unsubscribe", "optout", "opt-out", ...
})
```

**`urlparse` for domain extraction** — already imported on line 10:
```python
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
```
Use `urlparse(url).netloc.lower()` to extract domain. Strip `www.` prefix by checking `netloc.startswith("www.")`.

**Error-safe URL parsing** (mirrors `_normalize_url()` lines 137–155):
```python
try:
    ...
except Exception:
    return False   # on parse error, don't filter
```

**Private helper before `_is_boilerplate_link()`** — `_normalize_url()` is placed before `_is_boilerplate_link()` (lines 126–168). `_is_boilerplate_url()` follows the same placement order (URL helper → link filter).

**Removing calls, not the data model** — `ParsedEmail.links` field stays in the dataclass (removing it would be a breaking API change). Only stop populating it. Update its comment.

---

## STEP-BY-STEP TASKS

### TASK 1: ADD `_SOCIAL_DOMAINS` constant — `ingestion/email_parser.py`

After the closing `})` of `_TRACKING_PARAMS` (currently after line 96), add:

```python
# Base domains for social platform links — used by _is_boilerplate_url().
# Links to these domains within sections are structural (share buttons, profile icons),
# not story destinations. Stored as bare domains (no www. prefix).
_SOCIAL_DOMAINS = frozenset({
    "twitter.com", "x.com", "t.co",
    "facebook.com", "fb.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com", "youtu.be",
    "tiktok.com",
})
```

- **VALIDATE**: `python -c "from ingestion.email_parser import _SOCIAL_DOMAINS; assert 'twitter.com' in _SOCIAL_DOMAINS; assert 'x.com' in _SOCIAL_DOMAINS; print('SOCIAL_DOMAINS OK')"`

---

### TASK 2: ADD `_is_boilerplate_url()` function — `ingestion/email_parser.py`

Add immediately after `_normalize_url()` (after its closing `except` block, before `def _is_boilerplate_link`):

```python
def _is_boilerplate_url(url: str) -> bool:
    """Return True if this URL points to a navigation/infrastructure destination.

    Used within content sections where anchor text is not a reliable signal —
    inline story links often have generic anchor text ('read more', 'here') and
    must not be filtered. Only URL structure and destination domain are checked.

    Checks:
    - Email management URL fragments (unsubscribe, preferences, etc.)
    - Social platform domains (share buttons, profile icons)
    """
    url_lower = url.lower()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    try:
        netloc = urlparse(url).netloc.lower()
        bare = netloc[4:] if netloc.startswith("www.") else netloc
        if bare in _SOCIAL_DOMAINS:
            return True
    except Exception:
        pass
    return False
```

- **GOTCHA**: `_BOILERPLATE_URL_FRAGMENTS` substring check is on the full URL string (same pattern as existing `_is_boilerplate_link()`). The social domain check parses just the netloc for precision.
- **GOTCHA**: `netloc[4:]` strips `www.` prefix (4 chars). This works for `www.twitter.com` → `twitter.com`. It will NOT incorrectly strip `www2.` since that doesn't start with `www.`.
- **VALIDATE**: see Level 2 validation commands

---

### TASK 3: UPDATE link filter in `_extract_sections()` — `ingestion/email_parser.py`

Find the link extraction loop in `_extract_sections()`. Change the single filter call:

**Current** (line 246):
```python
        for anchor, url in _MD_LINK_RE.findall(sec):
            if _is_boilerplate_link(url, anchor):
                continue
```

**Replace with:**
```python
        for anchor, url in _MD_LINK_RE.findall(sec):
            if _is_boilerplate_url(url):
                continue
```

- **IMPACT**: Links with anchor text `"read more"`, `"learn more"`, `"here"`, `"click here"`, `"find out more"`, etc. pointing to real content URLs are now preserved. Social share links (twitter.com, etc.) are still dropped via domain check. Email management links are still dropped via URL fragment check.
- **VALIDATE**: See Level 3 validation commands.

---

### TASK 4: REMOVE dead global link extraction from `parse_emails()` — `ingestion/email_parser.py`

**4a. Remove global links in plain+html branch.**

Current (lines 355–367):
```python
        if plain_text is not None:
            body = plain_text
            # Still extract links and sections from HTML part if present alongside plain text
            if html_text is not None:
                try:
                    html_soup = BeautifulSoup(html_text, "lxml")
                    links = _extract_links(html_soup)
                except Exception:
                    pass
                try:
                    sections = _extract_sections(html_text)
                except Exception:
                    sections = []
```

Replace with:
```python
        if plain_text is not None:
            body = plain_text
            # Extract sections from HTML part if present alongside plain text
            if html_text is not None:
                try:
                    sections = _extract_sections(html_text)
                except Exception:
                    sections = []
```

**4b. Remove global links in html-only branch.**

Current (lines 368–376):
```python
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            links = _extract_links(soup)   # extract BEFORE stripping (kept for fallback)
            _strip_noise(soup)
            body = _html_to_text(str(soup))
            try:
                sections = _extract_sections(html_text)
            except Exception:
                sections = []
```

Replace with:
```python
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            _strip_noise(soup)
            body = _html_to_text(str(soup))
            try:
                sections = _extract_sections(html_text)
            except Exception:
                sections = []
```

**4c. Remove `links` initialization and pass `links=[]` explicitly.**

Remove `links: list[dict] = []` initialization (currently line 352).

In the `ParsedEmail(...)` constructor call, change `links=links` to `links=[]`:
```python
        results.append(
            ParsedEmail(
                subject=subject,
                sender=sender,
                date=date_parsed,
                body=body,
                links=[],    # links are section-local; see sections field
                sections=sections,
            )
        )
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('parse_emails import OK')"`

---

### TASK 5: REMOVE `_extract_links()` function — `ingestion/email_parser.py`

Remove the entire `_extract_links()` function definition (currently lines 277–287):

```python
def _extract_links(soup: BeautifulSoup) -> list[dict]:
    """Extract all non-mailto hyperlinks with non-empty anchor text from a BeautifulSoup tree."""
    links = []
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        if not url or url.startswith("mailto:"):
            continue
        anchor_text = a.get_text(strip=True)
        if anchor_text and not _is_boilerplate_link(url, anchor_text):
            links.append({"url": url, "anchor_text": anchor_text})
    return links
```

- **GOTCHA**: After Tasks 4a and 4b, this function has zero callers. Removing it is safe.
- **GOTCHA**: `BeautifulSoup` import on line 13 is still used by `_strip_noise()` (which calls `soup.find_all(...)`) — do NOT remove the import.
- **VALIDATE**: `python -c "from ingestion.email_parser import parse_emails; print('import OK — _extract_links removed')"`

---

### TASK 6: UPDATE `ParsedEmail.links` field comment — `ingestion/email_parser.py`

Change the comment on the `links` field in the `ParsedEmail` dataclass:

**Current:**
```python
    links: list[dict] = field(default_factory=list)  # [{url, anchor_text}] — global, kept for fallback
```

**Replace with:**
```python
    links: list[dict] = field(default_factory=list)  # always empty — links are section-local; see sections field
```

- **VALIDATE**: `python -c "from ingestion.email_parser import ParsedEmail; e = ParsedEmail(subject='', sender='', date=None, body='x'); assert e.links == []; print('ParsedEmail.links default OK')"`

---

## VALIDATION COMMANDS

### Level 1: Import and constants check

```bash
python -c "
from ingestion.email_parser import _SOCIAL_DOMAINS, _is_boilerplate_url
assert 'twitter.com' in _SOCIAL_DOMAINS
assert 'x.com' in _SOCIAL_DOMAINS
assert 'facebook.com' in _SOCIAL_DOMAINS
assert 'linkedin.com' in _SOCIAL_DOMAINS
print('Level 1 PASSED: constants and import OK')
"
```

### Level 2: `_is_boilerplate_url()` unit tests

```bash
python -c "
from ingestion.email_parser import _is_boilerplate_url

# Must be filtered — email management URL fragments
assert _is_boilerplate_url('https://newsletter.com/unsubscribe?id=123')
assert _is_boilerplate_url('https://example.com/email-preferences')
assert _is_boilerplate_url('https://example.com/manage-subscription')

# Must be filtered — social platform domains
assert _is_boilerplate_url('https://twitter.com/intent/tweet?text=hello')
assert _is_boilerplate_url('https://www.facebook.com/sharer/sharer.php')
assert _is_boilerplate_url('https://linkedin.com/shareArticle')
assert _is_boilerplate_url('https://www.youtube.com/watch?v=abc')

# Must NOT be filtered — real content URLs with generic anchor text (this was the bug)
assert not _is_boilerplate_url('https://arxiv.org/abs/2401.01234')
assert not _is_boilerplate_url('https://openai.com/research/gpt-5')
assert not _is_boilerplate_url('https://techcrunch.com/2026/03/17/ai-news/')
assert not _is_boilerplate_url('https://github.com/anthropics/claude')
assert not _is_boilerplate_url('https://example.com/blog/article')

print('Level 2 PASSED: _is_boilerplate_url unit tests OK')
"
```

### Level 3: Inline generic-anchor links now preserved in `_extract_sections()`

```bash
python -c "
from ingestion.email_parser import _extract_sections

# Section with primary story link using generic anchor text — previously dropped, now kept
html = '''<html><body>
<h2>OpenAI Releases GPT-5 with Record Benchmark Performance</h2>
<p>OpenAI has released GPT-5, achieving state-of-the-art results on 12 major benchmarks.
The model shows significant improvements in reasoning and code generation tasks.
Researchers say this represents a step change in capability over previous generations.
<a href=\"https://openai.com/research/gpt-5\">Read more</a></p>
</body></html>'''

sections = _extract_sections(html)
assert len(sections) == 1, f'Expected 1 section, got {len(sections)}'
links = sections[0]['links']
assert len(links) == 1, f'Expected 1 link, got {len(links)}: {links}'
assert links[0]['url'] == 'https://openai.com/research/gpt-5', f'Wrong URL: {links[0][\"url\"]}'
assert links[0]['anchor_text'] == 'Read more', f'Wrong anchor: {links[0][\"anchor_text\"]}'
print('Level 3a PASSED: inline read-more link preserved')

# Social share link still filtered (URL-based, not anchor-based)
html2 = '''<html><body>
<h2>Anthropic Raises Series E Funding Round for Safety Research</h2>
<p>Anthropic announced a major funding round today, raising 2 billion dollars to accelerate
AI safety research and expand its model training capabilities significantly.
<a href=\"https://arxiv.org/abs/1234\">Learn more about the research</a>
<a href=\"https://twitter.com/intent/tweet?text=check+this+out\">Tweet this</a></p>
</body></html>'''

sections2 = _extract_sections(html2)
assert len(sections2) == 1, f'Expected 1 section, got {len(sections2)}'
links2 = sections2[0]['links']
assert len(links2) == 1, f'Expected 1 link (twitter dropped), got {len(links2)}: {links2}'
assert 'arxiv.org' in links2[0]['url'], f'Expected arxiv link, got {links2[0][\"url\"]}'
print('Level 3b PASSED: social share link still filtered, arxiv link kept')
"
```

### Level 4: `ParsedEmail.links` is always empty — no global link extraction

```bash
python -c "
# Verify _extract_links is gone
import inspect, ingestion.email_parser as m
assert not hasattr(m, '_extract_links'), '_extract_links should be removed'
print('Level 4a PASSED: _extract_links removed')

# Verify ParsedEmail.links is always empty
from ingestion.email_parser import ParsedEmail
e = ParsedEmail(subject='test', sender='test', date=None, body='test')
assert e.links == [], f'Expected empty links, got {e.links}'
print('Level 4b PASSED: ParsedEmail.links defaults to empty list')
"
```

### Level 5: Full pipeline — no regression in story count or sourceless count

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
```

Expected: `story_count` > 0; `Dropped N sourceless` count ≤ 68 (should be equal or lower, since more sections now have links); `Generated N entries` where N > 0.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_is_boilerplate_url` is importable from `ingestion.email_parser`
- [ ] `_SOCIAL_DOMAINS` contains `twitter.com`, `x.com`, `facebook.com`, `linkedin.com`
- [ ] `_is_boilerplate_url('https://arxiv.org/abs/1234')` returns `False`
- [ ] `_is_boilerplate_url('https://twitter.com/intent/tweet')` returns `True`
- [ ] `_is_boilerplate_url('https://example.com/unsubscribe')` returns `True`
- [ ] A section with `[Read more](https://real-article.com)` produces 1 link in `_extract_sections()` output
- [ ] `_extract_links` is not a module-level attribute of `ingestion.email_parser`
- [ ] `ParsedEmail.links` is always `[]` by default
- [ ] Full pipeline produces > 0 digest entries with no increase in sourceless count

---

## ROLLBACK CONSIDERATIONS

All changes are in `ingestion/email_parser.py`. To revert:
- Restore `if _is_boilerplate_link(url, anchor):` in `_extract_sections()`
- Restore `_extract_links()` function
- Restore `_extract_links()` calls in `parse_emails()`
- Restore `links: list[dict] = []` initialization and `links=links` in constructor
- Remove `_SOCIAL_DOMAINS` and `_is_boilerplate_url()`

## ACCEPTANCE CRITERIA

- [ ] `_is_boilerplate_url()` added and passes URL+domain check only (no anchor text)
- [ ] `_extract_sections()` uses `_is_boilerplate_url()` instead of `_is_boilerplate_link()`
- [ ] `_extract_links()` removed from `parse_emails()` and from module
- [ ] `ParsedEmail.links` always `[]` — links flow only through sections
- [ ] Inline "read more" / "learn more" / "here" links pointing to real URLs are preserved
- [ ] Social platform sharing links are still filtered (domain-based)
- [ ] Email management links are still filtered (URL fragment-based)
- [ ] Pipeline produces > 0 digest entries; sourceless count does not increase

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _SOCIAL_DOMAINS, _is_boilerplate_url
  assert 'twitter.com' in _SOCIAL_DOMAINS
  assert 'x.com' in _SOCIAL_DOMAINS
  assert 'facebook.com' in _SOCIAL_DOMAINS
  assert 'linkedin.com' in _SOCIAL_DOMAINS
  print('Level 1 PASSED: constants and import OK')
  "
  ```
  Expected output or result:
  ```
  Level 1 PASSED: constants and import OK
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _is_boilerplate_url
  assert _is_boilerplate_url('https://newsletter.com/unsubscribe?id=123')
  assert _is_boilerplate_url('https://example.com/email-preferences')
  assert _is_boilerplate_url('https://example.com/manage-subscription')
  assert _is_boilerplate_url('https://twitter.com/intent/tweet?text=hello')
  assert _is_boilerplate_url('https://www.facebook.com/sharer/sharer.php')
  assert _is_boilerplate_url('https://linkedin.com/shareArticle')
  assert _is_boilerplate_url('https://www.youtube.com/watch?v=abc')
  assert not _is_boilerplate_url('https://arxiv.org/abs/2401.01234')
  assert not _is_boilerplate_url('https://openai.com/research/gpt-5')
  assert not _is_boilerplate_url('https://techcrunch.com/2026/03/17/ai-news/')
  assert not _is_boilerplate_url('https://github.com/anthropics/claude')
  assert not _is_boilerplate_url('https://example.com/blog/article')
  print('Level 2 PASSED: _is_boilerplate_url unit tests OK')
  "
  ```
  Expected output or result:
  ```
  Level 2 PASSED: _is_boilerplate_url unit tests OK
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _extract_sections

  html = '''<html><body>
  <h2>OpenAI Releases GPT-5 with Record Benchmark Performance</h2>
  <p>OpenAI has released GPT-5, achieving state-of-the-art results on 12 major benchmarks.
  The model shows significant improvements in reasoning and code generation tasks.
  Researchers say this represents a step change in capability over previous generations.
  <a href=\"https://openai.com/research/gpt-5\">Read more</a></p>
  </body></html>'''

  sections = _extract_sections(html)
  assert len(sections) == 1, f'Expected 1 section, got {len(sections)}'
  links = sections[0]['links']
  assert len(links) == 1, f'Expected 1 link, got {len(links)}: {links}'
  assert links[0]['url'] == 'https://openai.com/research/gpt-5', f'Wrong URL: {links[0][\"url\"]}'
  assert links[0]['anchor_text'] == 'Read more', f'Wrong anchor: {links[0][\"anchor_text\"]}'
  print('Level 3a PASSED: inline read-more link preserved')

  html2 = '''<html><body>
  <h2>Anthropic Raises Series E Funding Round for Safety Research</h2>
  <p>Anthropic announced a major funding round today, raising 2 billion dollars to accelerate
  AI safety research and expand its model training capabilities significantly.
  <a href=\"https://arxiv.org/abs/1234\">Learn more about the research</a>
  <a href=\"https://twitter.com/intent/tweet?text=check+this+out\">Tweet this</a></p>
  </body></html>'''

  sections2 = _extract_sections(html2)
  assert len(sections2) == 1, f'Expected 1 section, got {len(sections2)}'
  links2 = sections2[0]['links']
  assert len(links2) == 1, f'Expected 1 link (twitter dropped), got {len(links2)}: {links2}'
  assert 'arxiv.org' in links2[0]['url'], f'Expected arxiv link, got {links2[0][\"url\"]}'
  print('Level 3b PASSED: social share link still filtered, arxiv link kept')
  "
  ```
  Expected output or result:
  ```
  Level 3a PASSED: inline read-more link preserved
  Level 3b PASSED: social share link still filtered, arxiv link kept
  ```

- Item to check:
  ```
  python -c "
  import inspect, ingestion.email_parser as m
  assert not hasattr(m, '_extract_links'), '_extract_links should be removed'
  print('Level 4a PASSED: _extract_links removed')

  from ingestion.email_parser import ParsedEmail
  e = ParsedEmail(subject='test', sender='test', date=None, body='test')
  assert e.links == [], f'Expected empty links, got {e.links}'
  print('Level 4b PASSED: ParsedEmail.links defaults to empty list')
  "
  ```
  Expected output or result:
  ```
  Level 4a PASSED: _extract_links removed
  Level 4b PASSED: ParsedEmail.links defaults to empty list
  ```

- Item to check:
  ```
  python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
  ```
  Expected output or result:
  Pipeline completes with `"story_count": N` where N > 0. `Dropped N sourceless story group(s)` count is ≤ 68 (equal or lower than pre-change baseline). `Generated N digest entry/entries` where N > 0.

---

## NOTES

- **Why not remove `_BOILERPLATE_ANCHORS`?** It is no longer used by `_extract_sections()` after this change. However, `_is_boilerplate_link()` still references it. Rather than cascading changes, leave `_BOILERPLATE_ANCHORS`, `_BOILERPLATE_ANCHOR_SUBSTRINGS`, and `_is_boilerplate_link()` intact — they are not harmful and may be useful for other purposes (e.g., global link extraction if ever needed for a different feature).
- **Why domain-check for social, not URL-pattern?** Social sharing links consistently come from the social platform's own domain (twitter.com/intent/tweet, linkedin.com/shareArticle). Domain-level blocking is simpler and covers the cases previously caught by anchor text like "tweet this", "share on facebook". It also correctly allows links TO articles about these platforms hosted elsewhere.
- **Why does `sourceless count` potentially decrease?** Before this change, story sections whose only link had generic anchor text ("read more") were stripped of that link, making the section link-less. The section's StoryChunk had `links=[]`. When deduplicated into a cluster, if ALL chunks in that cluster had `links=[]`, the group was dropped as sourceless. After this change, those sections carry their link, reducing sourceless drops.
- **Confidence score: 9/10** — isolated to two clear changes in one function, plus dead code removal. The only risk is an unexpected social or navigation domain not covered by `_SOCIAL_DOMAINS`, which the section-level content filters (`_MIN_SECTION_CHARS`, `_is_boilerplate_segment()`) partially mitigate.
