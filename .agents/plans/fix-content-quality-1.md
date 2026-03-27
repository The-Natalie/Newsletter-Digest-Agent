# Feature: fix-content-quality-1 — Tighten Section and Link Boilerplate Filtering

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

## Feature Description

Newsletter-shell sections are passing through `_extract_sections()` and becoming story groups because `_BOILERPLATE_SEGMENT_SIGNALS` only covers 9 basic sponsor phrases. Missing categories: subscription management, advertising-pitch content, podcast/media availability, referral/promo, and newsletter meta. Additionally, `_BOILERPLATE_ANCHORS` uses exact string matching, so anchor text variants like "update your preferences here" slip through.

## Problem Statement (confirmed via diagnostic)

Sections reaching the pipeline that should be filtered:

| Example section text | Missing signal |
|---|---|
| `"Manage your subscriptions to our other newsletters..."` | subscription management |
| `"Update your email preferences or unsubscribe here"` | subscription management |
| `"Don't unsubscribe—update your preferences..."` | subscription management |
| `"© 2026 Jack Clark ... Unsubscribe"` | footer/copyright |
| `"Advertise to 675K+ readers"` | advertising pitch |
| `"Want to reach 675,000 AI-hungry readers"` | advertising pitch |
| `"Take The Deep View with you on the go! ... podcast"` | podcast availability |
| `"You're currently a free subscriber to Import AI..."` | subscription meta |
| `"Share your referral link below for free TLDR swag!"` | referral/promo |
| `"*Asterisk = from our partners ... Advertise to 675K+"` | advertising |

**Important false-positive edge case (confirmed):** AI Weekly's "Europe's AI Champion Play" section matches `"unsubscribe"` because the section spans both the real story text and an appended footer. Bare `"unsubscribe"` as a segment signal would incorrectly filter this story. The safe fix is to use **multi-word phrases specific to footer contexts** rather than bare single words.

**Anchor text gap:** `_BOILERPLATE_ANCHORS` uses exact matching. "update your preferences here", "update your email preferences", "manage your subscriptions" are not in the set, so these links pass through and become sources.

## Scope

- In scope: `ingestion/email_parser.py` — `_BOILERPLATE_SEGMENT_SIGNALS` expansion, new `_BOILERPLATE_ANCHOR_SUBSTRINGS` constant, update to `_is_boilerplate_link()`
- Out of scope: `embedder.py`, `deduplicator.py`, `ai/claude_client.py`, all other files

## Solution Statement

1. Expand `_BOILERPLATE_SEGMENT_SIGNALS` with multi-word phrases that unambiguously identify non-story sections. Avoid bare single words (`"unsubscribe"`, `"podcast"`) that appear in real story text.
2. Add `_BOILERPLATE_ANCHOR_SUBSTRINGS` — a tuple of substrings for partial anchor-text matching — to catch preference/subscription link variants without enumerating every exact phrase.
3. Update `_is_boilerplate_link()` to check `_BOILERPLATE_ANCHOR_SUBSTRINGS` after the existing exact-match check.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` — full file; specifically `_BOILERPLATE_SEGMENT_SIGNALS` (lines 72–83), `_BOILERPLATE_ANCHORS` (lines 35–65), `_is_boilerplate_link()` (lines 86–94), `_is_boilerplate_segment()` (lines 107–110)

### Patterns to Follow

**Existing segment signal check (line 109–110):**
```python
def _is_boilerplate_segment(text: str) -> bool:
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

**Existing link check (lines 86–94):**
```python
def _is_boilerplate_link(url: str, anchor_text: str) -> bool:
    url_lower = url.lower()
    anchor_lower = anchor_text.lower().strip()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    if anchor_lower in _BOILERPLATE_ANCHORS:
        return True
    return False
```

---

## STEP-BY-STEP TASKS

### TASK 1: UPDATE `ingestion/email_parser.py` — expand `_BOILERPLATE_SEGMENT_SIGNALS`

Replace the current `_BOILERPLATE_SEGMENT_SIGNALS` tuple with the expanded version below.

**Current (lines 72–83):**
```python
# Substrings that identify sponsor or shell segments — checked against lowercase text.
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

**Replace with:**
```python
# Substrings that identify sponsor or shell segments — checked against lowercase text.
# All entries are multi-word phrases to avoid false positives on real story text that
# incidentally contains a single boilerplate word (e.g. a story that mentions "unsubscribe"
# as part of a longer sentence is not filtered; a footer that says
# "manage your subscriptions" is).
_BOILERPLATE_SEGMENT_SIGNALS = (
    # Sponsorship / advertising
    "sponsored by",
    "brought to you by",
    "presented by",
    "this newsletter is supported by",
    "this issue is sponsored",
    "our sponsor",
    "a word from our sponsor",
    "advertisement",
    "advertorial",
    "advertise to",
    "to advertise with",
    "reach our audience",
    "want to reach our",
    "advertising opportunities",
    "advertiser reach",
    # Subscription management / footer
    "manage your subscriptions",
    "manage your email",
    "update your email preferences",
    "email preferences or unsubscribe",
    "don't unsubscribe",
    "free subscriber to",
    "currently a free subscriber",
    "support this newsletter",
    "all rights reserved",
    # Podcast / media availability
    "available as a podcast",
    "available on podcast",
    "listen to the full episode",
    "listen to this week",
    "with you on the go",
    # Referral / promotional
    "referral link",
    "free swag",
    # Generic newsletter meta
    "forward this email",
    "share this newsletter",
    "recommend this newsletter",
)
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('ok')"`

### TASK 2: UPDATE `ingestion/email_parser.py` — add `_BOILERPLATE_ANCHOR_SUBSTRINGS`

After the `_BOILERPLATE_ANCHORS` frozenset block and before `_is_boilerplate_link()`, add:

```python
# Substring patterns for anchor text that can't be enumerated exactly.
# Checked with `in` against lowercased anchor text. Keep entries specific enough
# to avoid false positives — each should unambiguously indicate a footer/admin link.
_BOILERPLATE_ANCHOR_SUBSTRINGS = (
    "your preferences",
    "your subscription",
    "your email preferences",
    "manage your email",
    "manage your subscriptions",
)
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('ok')"`

### TASK 3: UPDATE `ingestion/email_parser.py` — add substring check to `_is_boilerplate_link()`

Update `_is_boilerplate_link()` to also check `_BOILERPLATE_ANCHOR_SUBSTRINGS`:

**Current:**
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

**Replace with:**
```python
def _is_boilerplate_link(url: str, anchor_text: str) -> bool:
    """Return True if this link is a boilerplate footer/navigation link, not a story link."""
    url_lower = url.lower()
    anchor_lower = anchor_text.lower().strip()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    if anchor_lower in _BOILERPLATE_ANCHORS:
        return True
    if any(sub in anchor_lower for sub in _BOILERPLATE_ANCHOR_SUBSTRINGS):
        return True
    return False
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('ok')"`

---

## VALIDATION COMMANDS

### Level 1: Import check

```bash
python -c "import ingestion.email_parser; print('email_parser OK')"
```

### Level 2: Segment filter unit tests

```bash
python -c "
from ingestion.email_parser import _is_boilerplate_segment

# Must be filtered
assert _is_boilerplate_segment('Manage your subscriptions to our other newsletters'), 'subscription management'
assert _is_boilerplate_segment('Update your email preferences or unsubscribe here'), 'email preferences footer'
assert _is_boilerplate_segment('Advertise to 675K+ AI enthusiasts'), 'advertising pitch'
assert _is_boilerplate_segment('Take The Deep View with you on the go! Exclusive podcast interviews'), 'podcast availability'
assert _is_boilerplate_segment('Share your referral link below with friends to get free TLDR swag!'), 'referral promo'
assert _is_boilerplate_segment(\"You're currently a free subscriber to Import AI\"), 'subscription meta'
assert _is_boilerplate_segment('Don\\'t unsubscribe—update your preferences instead'), 'preference mgmt'

# Must NOT be filtered (real story text)
assert not _is_boilerplate_segment('LeCun is positioning AMI as something Silicon Valley cannot easily replicate for AI infrastructure'), 'real story'
assert not _is_boilerplate_segment('OpenAI released GPT-5 today with significantly improved reasoning capabilities'), 'real story'
assert not _is_boilerplate_segment('Researchers at Google published a paper on more efficient transformer architectures'), 'real story'
print('Segment filter unit tests PASSED')
"
```

### Level 3: Anchor substring filter unit tests

```bash
python -c "
from ingestion.email_parser import _is_boilerplate_link

# Must be filtered
assert _is_boilerplate_link('https://example.com/prefs', 'update your preferences here'), 'pref variant 1'
assert _is_boilerplate_link('https://example.com/prefs', 'update your email preferences'), 'pref variant 2'
assert _is_boilerplate_link('https://example.com/subs', 'manage your subscriptions'), 'subs variant'
assert _is_boilerplate_link('https://example.com/email', 'manage your email settings'), 'email settings'

# Must NOT be filtered (real story links)
assert not _is_boilerplate_link('https://arxiv.org/paper123', 'New transformer architecture paper'), 'real link 1'
assert not _is_boilerplate_link('https://openai.com/blog/gpt5', 'GPT-5 release announcement'), 'real link 2'
print('Anchor substring filter unit tests PASSED')
"
```

### Level 4: Section extraction — boilerplate sections produce 0 output

```bash
python -c "
from ingestion.email_parser import _extract_sections

# HTML containing only boilerplate sections
html = '''<html><body>
<p>Manage your subscriptions to our other newsletters. Or if TLDR is not for you, unsubscribe here.</p>
<hr/>
<p>Advertise to 675,000+ AI professionals. Reach our audience of engineers and researchers.</p>
<hr/>
<p>Take The Deep View with you on the go! Listen to the full episode on our podcast.</p>
<hr/>
<p>Share your referral link below with friends to get free TLDR swag!</p>
</body></html>'''
sections = _extract_sections(html)
assert len(sections) == 0, f'Expected 0 sections, got {len(sections)}: {[s[\"text\"][:60] for s in sections]}'
print('Boilerplate-only HTML produces 0 sections PASSED')
"
```

### Level 5: Section extraction — real story sections survive

```bash
python -c "
from ingestion.email_parser import _extract_sections

# HTML containing a real story followed by a boilerplate footer
html = '''<html><body>
<h2>OpenAI Releases GPT-5 with Improved Reasoning</h2>
<p>OpenAI announced GPT-5 today, claiming significant improvements in multi-step reasoning and code generation. The model is available via API immediately. <a href=\"https://openai.com/blog/gpt5\">Read the announcement</a>.</p>
<hr/>
<p>Manage your subscriptions to our other newsletters. Or unsubscribe here.</p>
</body></html>'''
sections = _extract_sections(html)
assert len(sections) == 1, f'Expected 1 section (real story only), got {len(sections)}: {[s[\"text\"][:60] for s in sections]}'
assert 'openai' in sections[0]['text'].lower(), 'Real story text preserved'
print('Real story survives boilerplate filtering PASSED')
"
```

### Level 6: Full pipeline run

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count)"
```

### Level 7: Output quality check — known bad headlines absent

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | python -c "
import sys, json, re
output = sys.stdin.read()
# Extract JSON from output (last {...} block)
match = re.search(r'\{.*\}', output, re.DOTALL)
if not match:
    print('No JSON found in output')
    sys.exit(1)
data = json.loads(match.group())
headlines = [s.get('headline', '').lower() for s in data.get('stories', [])]

bad_patterns = [
    'subscription management', 'unsubscribe', 'advertising opportunit',
    'advertiser reach', 'newsletter advertising', 'podcast episode',
    'listen online', 'weekly digest', 'referral link',
    'email preference', 'newsletter frequency',
]
failures = []
for h in headlines:
    for pat in bad_patterns:
        if pat in h:
            failures.append(f'BAD HEADLINE: {h!r} (matched {pat!r})')
if failures:
    print('QUALITY CHECK FAILED:')
    for f in failures:
        print(' ', f)
    sys.exit(1)
else:
    print(f'Quality check PASSED: {len(headlines)} headlines, none matched bad patterns')
"
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_is_boilerplate_segment()` rejects subscription management content
- [ ] `_is_boilerplate_segment()` rejects advertising-pitch content
- [ ] `_is_boilerplate_segment()` rejects podcast/media availability content
- [ ] `_is_boilerplate_segment()` rejects referral/promo content
- [ ] `_is_boilerplate_link()` rejects "update your preferences here" and similar variants
- [ ] Real story sections (e.g., an AI news story) are NOT filtered
- [ ] No digest entry headline matches the known bad patterns from the diagnostic
- [ ] Each digest entry headline describes a real news event or development

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `python -c "import ingestion.email_parser; print('email_parser OK')"`
  Expected output or result:
  ```
  email_parser OK
  ```

- Item to check:
  Segment filter unit tests (Level 2)
  Expected output or result:
  ```
  Segment filter unit tests PASSED
  ```

- Item to check:
  Anchor substring filter unit tests (Level 3)
  Expected output or result:
  ```
  Anchor substring filter unit tests PASSED
  ```

- Item to check:
  Boilerplate-only HTML produces 0 sections (Level 4)
  Expected output or result:
  ```
  Boilerplate-only HTML produces 0 sections PASSED
  ```

- Item to check:
  Real story survives boilerplate filtering (Level 5)
  Expected output or result:
  ```
  Real story survives boilerplate filtering PASSED
  ```

- Item to check:
  Full pipeline run stage summary (Level 6): `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count)"`
  Expected output or result:
  Stage 5 generates > 0 entries; output includes `"story_count": <N>` where N > 0.

- Item to check:
  Output quality check (Level 7): no headlines match known bad patterns
  Expected output or result:
  ```
  Quality check PASSED: <N> headlines, none matched bad patterns
  ```

- Item to check:
  File `ingestion/email_parser.py` modified — `_BOILERPLATE_SEGMENT_SIGNALS` expanded, `_BOILERPLATE_ANCHOR_SUBSTRINGS` added, `_is_boilerplate_link()` updated.
  Expected output or result:
  Import passes (confirmed by Level 1) and all unit tests pass (Levels 2–5).

- Item to check:
  No digest entry headline describes subscription management, advertising, podcasts, or newsletter-shell content (manual review of full pipeline output)
  Expected output or result:
  Every headline in the digest JSON describes a real AI news event or development. None of the following patterns appear in headlines: "subscription", "unsubscribe", "advertising", "podcast", "newsletter frequency", "referral", "email preference".

---

## NOTES

- **False positive protection**: all new `_BOILERPLATE_SEGMENT_SIGNALS` entries are multi-word phrases. Single words like "unsubscribe" or "podcast" are intentionally excluded because they appear in real story text (confirmed by diagnostic: AI Weekly's "Europe's AI Champion Play" section contains "unsubscribe" appended from a footer).
- **Why `_BOILERPLATE_ANCHOR_SUBSTRINGS` uses substring matching**: anchor text variants for subscription preferences are unpredictable ("update your preferences here", "update your email preferences", "manage your email settings", etc.). Substring matching on "your preferences" and "your subscription" covers the family of variants without needing to enumerate every exact phrase.
- **"Merged unrelated items" problem**: improving section filtering will reduce this indirectly (fewer boilerplate sections means less diverse content for the embedder to accidentally cluster together). Any remaining merged entries may require a dedup threshold tuning pass in a future loop.
- **"with you on the go"** is the podcast availability signal for The Deep View. It's specific enough in the context of an email newsletter section — a real news story about mobile software would be more likely to say "on mobile" or "on your phone" than "with you on the go" in a section header.
