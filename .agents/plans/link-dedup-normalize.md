# Feature: link-dedup-normalize — URL Normalization and Section-Level Link Deduplication

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to the exact current link-extraction loop in `_extract_sections()` — it uses `seen_urls: set[str]` (raw URL dedup). This is the only loop that needs to change.

## Feature Description

Newsletter links frequently include tracking parameters (`utm_*`, `fbclid`, `mc_cid`, etc.) appended to the same underlying destination URL. The same article may be linked 3–5 times in one section with different tracking strings, producing noisy source lists downstream. This plan normalizes URLs by stripping known tracking parameters, lowercasing scheme/host, and stripping trailing slashes — then deduplicates per section by normalized URL, keeping the longest anchor text when duplicates exist.

## User Story

As the pipeline,
I want section-level link lists to contain one clean entry per unique destination,
So that source attribution in the digest is precise, readable, and free of tracking noise.

## Problem Statement

In `_extract_sections()`, link deduplication is done by exact raw URL match (`seen_urls: set[str]`). Two links to the same article — one with `?utm_source=newsletter` appended and one without — are treated as distinct and both added to the section's link list. This propagates tracking URLs into `StoryChunk.links`, then into `StoryGroup.sources`, and ultimately into the digest output. It also inflates source counts and can cause different tracking variants of the same article to appear as separate sources.

## Scope

- In scope: `ingestion/email_parser.py` — add `_normalize_url()`, add `_TRACKING_PARAMS`, update link dedup loop in `_extract_sections()`
- Out of scope: `_extract_links()` (global fallback, not section-level), `processing/deduplicator.py` (`_build_sources()` cross-section dedup), `processing/embedder.py`, `ai/claude_client.py`, all other files

## Solution Statement

1. Add `_TRACKING_PARAMS` — a `frozenset` of known tracking parameter names to strip.
2. Add `_normalize_url(url)` — strips tracking params, lowercases scheme+host, strips trailing slash, drops fragment. Uses stdlib `urllib.parse` only — no new dependencies.
3. Replace the `seen_urls: set[str]` dedup loop in `_extract_sections()` with a `best_by_norm: dict[str, dict]` approach: normalize each URL, use normalized form as the dedup key, and when two links resolve to the same normalized destination keep the one with the longer anchor text. Store the normalized URL in the output `{"url": norm, "anchor_text": ...}` so tracking params don't propagate downstream.

## Feature Metadata

**Feature Type**: Enhancement / Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`
**Dependencies**: `urllib.parse` (stdlib — already available, no pip install needed)
**Assumptions**: Longer anchor text is a reliable proxy for "more meaningful" among already-filtered (non-boilerplate) anchors. Stripping the fragment (`#`) from normalized URLs is acceptable — two links to `article#section1` and `article#section2` should be treated as the same article for dedup purposes.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 1–10) — current imports: `re`, `email`, `logging`, `dataclasses`, `datetime`, `html2text`, `BeautifulSoup`. Add `from urllib.parse import urlparse, urlunparse, urlencode, parse_qs` here.
- `ingestion/email_parser.py` (lines 79–82) — `_SECTION_SPLIT_PATTERN`, `_MIN_SECTION_CHARS`, `_MD_LINK_RE` constants block. Add `_TRACKING_PARAMS` and `_normalize_url()` after this block.
- `ingestion/email_parser.py` (lines 188–210) — the link extraction loop inside `_extract_sections()`. This is the **only loop that changes**:
  ```python
  # CURRENT — dedup by raw URL:
  links = []
  seen_urls: set[str] = set()
  for anchor, url in _MD_LINK_RE.findall(sec):
      if url not in seen_urls and not _is_boilerplate_link(url, anchor):
          seen_urls.add(url)
          links.append({"url": url, "anchor_text": anchor})
  ```
- `ingestion/email_parser.py` (lines 224–234) — `_extract_links()`. **Do NOT change** — out of scope for this loop.
- `processing/deduplicator.py` (lines 18–34) — `_build_sources()` deduplicates by raw URL across chunks. **Do NOT change** — out of scope. After this loop, URLs arriving here will already be normalized, so cross-chunk dedup will naturally benefit too.

### New Files to Create

None. All changes are within `ingestion/email_parser.py`.

### Patterns to Follow

**Constant block pattern** (email_parser.py lines 79–82):
```python
_SECTION_SPLIT_PATTERN = re.compile(r'\n{2,}|^\s*[-*_]{3,}\s*$', re.MULTILINE)
_MIN_SECTION_CHARS = 100
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
```
Add `_TRACKING_PARAMS` immediately after this block as a `frozenset` (matches `_BOILERPLATE_URL_FRAGMENTS` pattern on line 30).

**frozenset constant pattern** (email_parser.py line 30):
```python
_BOILERPLATE_URL_FRAGMENTS = frozenset({
    "unsubscribe", "optout", "opt-out", ...
})
```

**Private helper function placement**: Add `_normalize_url()` just before `_is_boilerplate_link()` (currently line 111) so it is available when `_extract_sections()` calls it.

**Error-safe URL parsing**: Wrap `urlparse` logic in `try/except Exception: return url` — mirrors the `try/except Exception: sections = []` defensive pattern used in `parse_emails()` (lines 327–335).

**Logging pattern** (email_parser.py line 14):
```python
logger = logging.getLogger(__name__)
```
No new logger needed; `_normalize_url()` should not log (hot path, called per-link).

---

## STEP-BY-STEP TASKS

### TASK 1: ADD import — `urllib.parse` to `ingestion/email_parser.py`

After the existing `from datetime import datetime` import (line 8), add:

```python
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
```

- **PATTERN**: stdlib imports grouped with other stdlib imports (lines 3–9)
- **GOTCHA**: Do NOT add to requirements.txt — `urllib.parse` is stdlib
- **VALIDATE**: `python -c "from ingestion.email_parser import _normalize_url; print('import OK')"`

---

### TASK 2: ADD `_TRACKING_PARAMS` constant to `ingestion/email_parser.py`

After the `_MD_LINK_RE` line (currently line 81), add:

```python
# Tracking/analytics query parameters stripped during URL normalization.
# utm_* prefix is handled separately (prefix match). Entries here are exact param names.
_TRACKING_PARAMS = frozenset({
    # Click IDs
    "fbclid", "gclid", "msclkid", "yclid", "twclid", "igshid",
    # Email platform tracking
    "mc_cid", "mc_eid",          # Mailchimp
    "_hsenc", "_hsmi",           # HubSpot
    "mkt_tok",                   # Marketo
    # Social / referral
    "li_fat_id",                 # LinkedIn
    "ref",                       # generic referral
})
```

- **GOTCHA**: Do NOT include `source` or `medium` alone — they appear as legitimate non-tracking params (e.g., `?source=github`). Only `utm_source` / `utm_medium` (caught by `utm_` prefix) should be stripped.
- **VALIDATE**: `python -c "from ingestion.email_parser import _TRACKING_PARAMS; assert 'fbclid' in _TRACKING_PARAMS; assert 'ref' in _TRACKING_PARAMS; print('TRACKING_PARAMS OK')"`

---

### TASK 3: ADD `_normalize_url()` function to `ingestion/email_parser.py`

Add immediately before `_is_boilerplate_link()` (currently line 111):

```python
def _normalize_url(url: str) -> str:
    """Strip tracking parameters and normalize URL for deduplication.

    - Removes utm_* parameters and known tracking params (_TRACKING_PARAMS).
    - Lowercases scheme and host.
    - Strips trailing slash from path (preserves bare '/').
    - Drops the fragment (#section) — two links to the same page with different
      anchors are treated as the same destination.

    Returns the original url unchanged on any parse error.
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)
        filtered = {
            k: v for k, v in params.items()
            if not k.startswith("utm_") and k not in _TRACKING_PARAMS
        }
        clean_query = urlencode(filtered, doseq=True)
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            clean_query,
            "",  # strip fragment
        ))
    except Exception:
        return url
```

- **GOTCHA**: `parse_qs` returns `{key: [value, ...]}` (lists). `urlencode(..., doseq=True)` handles this correctly. Do NOT use `parse_qsl` here — `parse_qs` + `doseq=True` is the correct pair.
- **GOTCHA**: `parsed.path.rstrip("/") or "/"` handles the case where path is `""` or `"/"` — both normalize to `"/"`.
- **GOTCHA**: `parsed.params` is the semicolon-separated URL parameters segment (rarely used), not query params — pass it through unchanged.
- **VALIDATE**: See Level 2 validation commands below.

---

### TASK 4: UPDATE link dedup loop in `_extract_sections()` — `ingestion/email_parser.py`

Replace the existing link extraction block inside `_extract_sections()` (lines 194–200):

**Current:**
```python
        # Extract links from inline markdown syntax
        links = []
        seen_urls: set[str] = set()
        for anchor, url in _MD_LINK_RE.findall(sec):
            if url not in seen_urls and not _is_boilerplate_link(url, anchor):
                seen_urls.add(url)
                links.append({"url": url, "anchor_text": anchor})
```

**Replace with:**
```python
        # Extract links from inline markdown syntax.
        # Normalize URLs before deduplication: strip tracking params, lowercase scheme/host.
        # When multiple links share the same normalized destination, keep the longest anchor text.
        best_by_norm: dict[str, dict] = {}
        for anchor, url in _MD_LINK_RE.findall(sec):
            if _is_boilerplate_link(url, anchor):
                continue
            norm = _normalize_url(url)
            if norm not in best_by_norm:
                best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
            elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
                best_by_norm[norm]["anchor_text"] = anchor
        links = list(best_by_norm.values())
```

- **KEY CHANGE**: Dedup key is `norm` (normalized URL) not raw `url`. Output `"url"` field stores the normalized URL, stripping tracking params from all downstream consumers.
- **KEY CHANGE**: `elif len(anchor) > len(...)` — longer anchor text wins when two links share the same normalized destination.
- **GOTCHA**: `dict` insertion order is preserved in Python 3.7+ — `list(best_by_norm.values())` preserves the order links were first encountered.
- **GOTCHA**: The condition changed from `if url not in seen_urls and not _is_boilerplate_link(...)` to `if _is_boilerplate_link(...): continue` + separate norm check. Logic is equivalent except dedup is now by `norm`.
- **VALIDATE**: See Level 3 validation commands below.

---

## VALIDATION COMMANDS

### Level 1: Import and constant checks

```bash
python -c "
from ingestion.email_parser import _normalize_url, _TRACKING_PARAMS
assert 'fbclid' in _TRACKING_PARAMS
assert 'ref' in _TRACKING_PARAMS
assert 'mc_cid' in _TRACKING_PARAMS
assert 'source' not in _TRACKING_PARAMS
assert 'medium' not in _TRACKING_PARAMS
print('Level 1 PASSED: imports and constants OK')
"
```

### Level 2: `_normalize_url()` unit tests

```bash
python -c "
from ingestion.email_parser import _normalize_url

# UTM stripping
assert _normalize_url('https://example.com/article?utm_source=newsletter&utm_medium=email') == 'https://example.com/article', repr(_normalize_url('https://example.com/article?utm_source=newsletter&utm_medium=email'))

# fbclid stripping
assert _normalize_url('https://example.com/article?fbclid=abc123') == 'https://example.com/article', repr(_normalize_url('https://example.com/article?fbclid=abc123'))

# ref stripping
assert _normalize_url('https://example.com/article?ref=tldr') == 'https://example.com/article', repr(_normalize_url('https://example.com/article?ref=tldr'))

# Mixed: strip tracking, keep real param
assert _normalize_url('https://example.com/search?q=ai&utm_source=news') == 'https://example.com/search?q=ai', repr(_normalize_url('https://example.com/search?q=ai&utm_source=news'))

# Trailing slash normalization
assert _normalize_url('https://example.com/article/') == 'https://example.com/article', repr(_normalize_url('https://example.com/article/'))

# Root path preserved
assert _normalize_url('https://example.com/') == 'https://example.com/', repr(_normalize_url('https://example.com/'))

# Fragment stripped
assert _normalize_url('https://example.com/article#section1') == 'https://example.com/article', repr(_normalize_url('https://example.com/article#section1'))

# Host lowercased
assert _normalize_url('https://Example.COM/article') == 'https://example.com/article', repr(_normalize_url('https://Example.COM/article'))

# No-op: clean URL unchanged (empty query)
assert _normalize_url('https://example.com/article') == 'https://example.com/article', repr(_normalize_url('https://example.com/article'))

# Error safety: malformed URL returned unchanged
result = _normalize_url('not-a-url')
assert result == 'not-a-url', repr(result)

print('Level 2 PASSED: _normalize_url unit tests OK')
"
```

### Level 3: Section-level deduplication unit test

```bash
python -c "
from ingestion.email_parser import _extract_sections

# Two links to the same article with different UTM variants and a plain link.
# The plain (clean) URL and UTM variant normalize identically.
# Anchor 'Read the full OpenAI report here' (35 chars) > 'OpenAI report' (13 chars) → longer wins.
html = '''<html><body>
<p>OpenAI released its usage report this week, showing a major jump in API calls.
<a href=\"https://openai.com/report?utm_source=tldr&utm_medium=email\">OpenAI report</a>
The same article was covered by multiple sources.
<a href=\"https://openai.com/report?utm_source=aiweekly\">Read the full OpenAI report here</a>
<a href=\"https://openai.com/report\">OpenAI report</a>
A third newsletter also covered this important development in detail.</p>
</body></html>'''

sections = _extract_sections(html)
assert len(sections) == 1, f'Expected 1 section, got {len(sections)}'
links = sections[0]['links']
assert len(links) == 1, f'Expected 1 deduplicated link, got {len(links)}: {links}'
assert links[0]['url'] == 'https://openai.com/report', f'Expected clean URL, got {links[0][\"url\"]}'
assert links[0]['anchor_text'] == 'Read the full OpenAI report here', f'Expected longest anchor, got {links[0][\"anchor_text\"]}'
print('Level 3 PASSED: section-level dedup and anchor preference OK')
"
```

### Level 4: No sourceless regression — pipeline end-to-end

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
```

Expected: `story_count` > 0; `Dropped N sourceless` count does not increase vs. baseline (was 68 in the previous run). `Generated` shows > 0 entries.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_normalize_url` is importable from `ingestion.email_parser`
- [ ] `_TRACKING_PARAMS` contains `fbclid`, `ref`, `mc_cid` and does NOT contain `source` or `medium`
- [ ] `_normalize_url('https://example.com/article?utm_source=tldr')` returns `'https://example.com/article'`
- [ ] `_normalize_url('https://example.com/article/')` returns `'https://example.com/article'`
- [ ] A section with 3 tracking-variant links to the same article produces exactly 1 link with the longest anchor text
- [ ] Pipeline runs end-to-end with > 0 digest entries and no increase in sourceless story groups

---

## ROLLBACK CONSIDERATIONS

All changes are in one function and two new constants/functions in `ingestion/email_parser.py`. To revert: restore the original `seen_urls: set[str]` dedup loop in `_extract_sections()`, remove `_TRACKING_PARAMS`, remove `_normalize_url()`, remove the `urllib.parse` import.

## ACCEPTANCE CRITERIA

- [ ] `_normalize_url()` strips all `utm_*` parameters
- [ ] `_normalize_url()` strips all params in `_TRACKING_PARAMS`
- [ ] `_normalize_url()` preserves non-tracking query params
- [ ] `_normalize_url()` strips trailing slashes (preserving bare `/`)
- [ ] `_normalize_url()` strips URL fragments
- [ ] `_normalize_url()` lowercases scheme and host
- [ ] `_normalize_url()` returns original URL on parse error (no exception raised)
- [ ] Section with 3 tracking variants of one URL → 1 link in output
- [ ] Longest anchor text is kept when deduplicating
- [ ] Normalized (clean) URL stored in output link dict — no tracking params in `StoryChunk.links`
- [ ] Full pipeline produces > 0 digest entries with no regression in sourceless count

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _normalize_url, _TRACKING_PARAMS
  assert 'fbclid' in _TRACKING_PARAMS
  assert 'ref' in _TRACKING_PARAMS
  assert 'mc_cid' in _TRACKING_PARAMS
  assert 'source' not in _TRACKING_PARAMS
  assert 'medium' not in _TRACKING_PARAMS
  print('Level 1 PASSED: imports and constants OK')
  "
  ```
  Expected output or result:
  ```
  Level 1 PASSED: imports and constants OK
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _normalize_url

  assert _normalize_url('https://example.com/article?utm_source=newsletter&utm_medium=email') == 'https://example.com/article', repr(_normalize_url('https://example.com/article?utm_source=newsletter&utm_medium=email'))
  assert _normalize_url('https://example.com/article?fbclid=abc123') == 'https://example.com/article', repr(_normalize_url('https://example.com/article?fbclid=abc123'))
  assert _normalize_url('https://example.com/article?ref=tldr') == 'https://example.com/article', repr(_normalize_url('https://example.com/article?ref=tldr'))
  assert _normalize_url('https://example.com/search?q=ai&utm_source=news') == 'https://example.com/search?q=ai', repr(_normalize_url('https://example.com/search?q=ai&utm_source=news'))
  assert _normalize_url('https://example.com/article/') == 'https://example.com/article', repr(_normalize_url('https://example.com/article/'))
  assert _normalize_url('https://example.com/') == 'https://example.com/', repr(_normalize_url('https://example.com/'))
  assert _normalize_url('https://example.com/article#section1') == 'https://example.com/article', repr(_normalize_url('https://example.com/article#section1'))
  assert _normalize_url('https://Example.COM/article') == 'https://example.com/article', repr(_normalize_url('https://Example.COM/article'))
  assert _normalize_url('https://example.com/article') == 'https://example.com/article', repr(_normalize_url('https://example.com/article'))
  result = _normalize_url('not-a-url')
  assert result == 'not-a-url', repr(result)
  print('Level 2 PASSED: _normalize_url unit tests OK')
  "
  ```
  Expected output or result:
  ```
  Level 2 PASSED: _normalize_url unit tests OK
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _extract_sections

  html = '''<html><body>
  <p>OpenAI released its usage report this week, showing a major jump in API calls.
  <a href=\"https://openai.com/report?utm_source=tldr&utm_medium=email\">OpenAI report</a>
  The same article was covered by multiple sources.
  <a href=\"https://openai.com/report?utm_source=aiweekly\">Read the full OpenAI report here</a>
  <a href=\"https://openai.com/report\">OpenAI report</a>
  A third newsletter also covered this important development in detail.</p>
  </body></html>'''

  sections = _extract_sections(html)
  assert len(sections) == 1, f'Expected 1 section, got {len(sections)}'
  links = sections[0]['links']
  assert len(links) == 1, f'Expected 1 deduplicated link, got {len(links)}: {links}'
  assert links[0]['url'] == 'https://openai.com/report', f'Expected clean URL, got {links[0][\"url\"]}'
  assert links[0]['anchor_text'] == 'Read the full OpenAI report here', f'Expected longest anchor, got {links[0][\"anchor_text\"]}'
  print('Level 3 PASSED: section-level dedup and anchor preference OK')
  "
  ```
  Expected output or result:
  ```
  Level 3 PASSED: section-level dedup and anchor preference OK
  ```

- Item to check:
  ```
  python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
  ```
  Expected output or result:
  Pipeline completes with `"story_count": N` where N > 0. `Dropped N sourceless story group(s)` count is ≤ 68 (no increase vs. pre-change baseline). `Generated N digest entry/entries` where N > 0.

---

## NOTES

- **Why store normalized URL in output?** The raw tracked URL (`?utm_source=tldr`) has no value to the reader — the normalized form is the actual destination. Storing `norm` means tracking params never propagate into `StoryGroup.sources` or the digest JSON.
- **Why not also normalize in `_extract_links()`?** Out of scope per user constraint. `_extract_links()` populates `ParsedEmail.links` (global fallback, used when sections fail). This can be addressed in a later loop if needed.
- **Why not also normalize in `_build_sources()`?** Out of scope. After this change, `StoryChunk.links` will already contain normalized URLs, so `_build_sources()` cross-chunk dedup will naturally benefit without any change needed there.
- **`parse_qs` + `urlencode(doseq=True)`**: `parse_qs` returns `{key: [val1, val2]}`. `urlencode` with `doseq=True` handles multi-value params correctly. This is the stdlib-idiomatic approach.
- **Confidence score: 9.5/10** — the change is isolated to one loop in one function. The `urllib.parse` API is stable and well-understood. The only edge case risk is unusual URL formats (handled by the `try/except` safety net).
