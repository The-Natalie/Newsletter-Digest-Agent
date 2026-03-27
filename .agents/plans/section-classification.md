# Feature: section-classification — Infrastructure-Only Section Filtering

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to the exact current contents of `_BOILERPLATE_SEGMENT_SIGNALS` and `_MIN_SECTION_CHARS` in `email_parser.py`.

## Feature Description

Redesign section filtering in `_extract_sections()` so it drops only true newsletter infrastructure (unsubscribe management, referral systems, navigation, account/settings, legal/footer boilerplate) and retains all substantive content sections regardless of whether they are promotional, sponsor-related, or commercial. Add a minimum content length threshold to drop thin CTA-only sections that have no substantive body text.

## User Story

As the pipeline,
I want to filter only newsletter infrastructure sections (unsubscribe, preferences, referrals, navigation, legal),
So that sponsor tools, product announcements, reports, webinars, job listings, and discounts are retained as potential digest content.

## Problem Statement

The current `_BOILERPLATE_SEGMENT_SIGNALS` conflates two distinct categories:

**Category A — Newsletter infrastructure** (should drop):
Sections whose sole purpose is managing the newsletter subscription system: unsubscribe footers, preference management, referral growth prompts, view-in-browser links, legal/copyright notices.

**Category B — Content sections** (should keep, even if promotional):
Sections that describe something substantive — a sponsor tool, a product launch, a report or dataset, a webinar, a job posting, a discount offer. These have value for the reader and may belong in the digest.

The current implementation incorrectly drops Category B. Confirmed by diagnostic:

| Signal currently firing | Example section | Correct action |
|---|---|---|
| `"brought to you by"` | "GTC COVERAGE BROUGHT TO YOU BY IREN — For today's AI builders, time-to-compute is crucial. IREN is re..." | **KEEP** — substantive sponsor coverage |
| `"advertise to"` | "🍪 Treats to Try — *Asterisk = from our partners. Advertise to 675K+ readers here" | **KEEP** — partner/sponsor content section |
| `"to advertise with"` | "…and a whole lot more that you can read about here." (section with content plus ad pitch appended) | **KEEP** — real content with ad pitch appended |
| `"with you on the go"` | "Take The Deep View with you on the go! Exclusive interviews on The Deep View: Conversations podcast every Tuesday..." | **KEEP** — podcast/media announcement |
| `"manage your subscriptions"` | "Manage your subscriptions" link | **DROP** — pure infrastructure |
| `"referral link"` | "Share your referral link below for free TLDR swag!" | **DROP** — referral growth system |
| `"free subscriber to"` | "You're currently a free subscriber to Import AI..." | **DROP** — subscription meta |
| `"update your email preferences"` | Table-formatted footer with preference links | **DROP** — infrastructure footer |

## Scope

- In scope: `ingestion/email_parser.py` — `_BOILERPLATE_SEGMENT_SIGNALS` and `_MIN_SECTION_CHARS`
- Out of scope: link handling (`_BOILERPLATE_ANCHORS`, `_BOILERPLATE_ANCHOR_SUBSTRINGS`, `_is_boilerplate_link()`), `embedder.py`, `deduplicator.py`, `ai/claude_client.py`, all other files

## Solution Statement

1. **Replace `_BOILERPLATE_SEGMENT_SIGNALS`** with an infrastructure-only set. Remove all signals that target sponsor, advertising, podcast, and media content. Retain only signals that unambiguously identify subscription management, referral systems, and legal/footer boilerplate.

2. **Raise `_MIN_SECTION_CHARS` from 50 to 100**. Thin CTA-only sections (e.g., "Try Cursor AI today! Start free.") rarely exceed 100 chars; substantive sponsor descriptions, job listings, and announcements typically exceed 100 chars.

## Feature Metadata

**Feature Type**: Refactor / Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`
**Dependencies**: None
**Assumptions**: Substantive content sections (sponsor descriptions, job listings, webinar announcements) are typically 100+ characters. Pure CTAs and thin navigation prompts are typically under 100 characters.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 79–129) — `_MIN_SECTION_CHARS`, `_BOILERPLATE_SEGMENT_SIGNALS` (current 36-entry list), `_is_boilerplate_segment()`

### Patterns to Follow

**`_is_boilerplate_segment()` function — unchanged, only its data changes:**
```python
def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

**`_MIN_SECTION_CHARS` usage in `_extract_sections()` (line ~210):**
```python
if len(clean_text) < _MIN_SECTION_CHARS:
    continue
```

---

## STEP-BY-STEP TASKS

### TASK 1: UPDATE `ingestion/email_parser.py` — raise `_MIN_SECTION_CHARS`

Change:
```python
_MIN_SECTION_CHARS = 50
```
To:
```python
_MIN_SECTION_CHARS = 100
```

- **VALIDATE**: `python -c "from ingestion.email_parser import _MIN_SECTION_CHARS; assert _MIN_SECTION_CHARS == 100; print('MIN_SECTION_CHARS = 100 OK')"`

### TASK 2: UPDATE `ingestion/email_parser.py` — replace `_BOILERPLATE_SEGMENT_SIGNALS`

Replace the entire current `_BOILERPLATE_SEGMENT_SIGNALS` tuple with the infrastructure-only version below.

**Current** (lines 83–129, 36 entries):
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
    "podcast episode",
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

**Replace with** (infrastructure-only, 13 entries):
```python
# Substrings that identify newsletter infrastructure segments — checked against lowercase text.
# These are sections whose sole purpose is managing the subscription system, referral
# growth, or legal/footer boilerplate. They contain no content value for the reader.
#
# NOT included: sponsor content, advertising copy, podcast/media availability, product
# announcements, reports, job listings, or discounts — these are content sections and
# are retained regardless of promotional nature. Very short pure-CTA sections are
# handled by _MIN_SECTION_CHARS instead.
_BOILERPLATE_SEGMENT_SIGNALS = (
    # Subscription management / preferences
    "manage your subscriptions",
    "manage your email",
    "update your email preferences",
    "email preferences or unsubscribe",
    "don't unsubscribe",
    "free subscriber to",
    "currently a free subscriber",
    "support this newsletter",
    "all rights reserved",
    # Referral / audience growth systems
    "referral link",
    # Navigation / sharing infrastructure
    "forward this email",
    "share this newsletter",
    "recommend this newsletter",
)
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('email_parser OK')"`

---

## VALIDATION COMMANDS

### Level 1: Constants check

```bash
python -c "
from ingestion.email_parser import _MIN_SECTION_CHARS, _BOILERPLATE_SEGMENT_SIGNALS
assert _MIN_SECTION_CHARS == 100, f'Expected 100, got {_MIN_SECTION_CHARS}'
assert len(_BOILERPLATE_SEGMENT_SIGNALS) == 13, f'Expected 13 signals, got {len(_BOILERPLATE_SEGMENT_SIGNALS)}'
# Confirm sponsor/ad signals are gone
assert 'sponsored by' not in _BOILERPLATE_SEGMENT_SIGNALS
assert 'brought to you by' not in _BOILERPLATE_SEGMENT_SIGNALS
assert 'advertise to' not in _BOILERPLATE_SEGMENT_SIGNALS
assert 'podcast episode' not in _BOILERPLATE_SEGMENT_SIGNALS
# Confirm infrastructure signals are present
assert 'manage your subscriptions' in _BOILERPLATE_SEGMENT_SIGNALS
assert 'referral link' in _BOILERPLATE_SEGMENT_SIGNALS
assert 'all rights reserved' in _BOILERPLATE_SEGMENT_SIGNALS
print('Constants check PASSED')
"
```

### Level 2: Infrastructure sections are dropped

```bash
python -c "
from ingestion.email_parser import _is_boilerplate_segment

# Must be dropped — infrastructure
assert _is_boilerplate_segment('Manage your subscriptions to our other newsletters. Unsubscribe here.')
assert _is_boilerplate_segment('Update your email preferences or unsubscribe from this list.')
assert _is_boilerplate_segment(\"Don't unsubscribe—just update your frequency preferences instead.\")
assert _is_boilerplate_segment(\"You're currently a free subscriber to Import AI. Support the newsletter.\")
assert _is_boilerplate_segment('Share your referral link below to earn free TLDR swag for your friends.')
assert _is_boilerplate_segment('Forward this email to a friend who might enjoy it.')
assert _is_boilerplate_segment('All rights reserved. © 2026 TechnologyAdvice, LLC. San Francisco, CA.')
print('Infrastructure drop test PASSED')
"
```

### Level 3: Content sections are kept

```bash
python -c "
from ingestion.email_parser import _is_boilerplate_segment

# Must be kept — substantive content even if promotional
assert not _is_boilerplate_segment('GTC COVERAGE BROUGHT TO YOU BY IREN. For AI builders, time-to-compute is crucial. IREN is redefining cloud infrastructure.')
assert not _is_boilerplate_segment('Sponsored by Cursor AI. Cursor is the AI code editor trusted by over 1 million developers. Write, edit, and debug code 10x faster.')
assert not _is_boilerplate_segment('NEW REPORT: State of AI in Enterprise 2026. Download the full dataset with survey results from 2,000 engineering leaders.')
assert not _is_boilerplate_segment('HIRING: Senior ML Engineer at Anthropic, San Francisco. Work on next-generation AI safety research. Competitive equity and salary.')
assert not _is_boilerplate_segment('Join our live webinar on AI agent architectures, April 15 at 2pm ET. Register now to secure your spot.')
assert not _is_boilerplate_segment('Take The Deep View with you on the go! Exclusive in-depth interviews on The Deep View: Conversations podcast every Tuesday.')
assert not _is_boilerplate_segment('SPECIAL OFFER: 3 months of Perplexity Pro free for newsletter readers. Use code AIWEEKLY at checkout.')
assert not _is_boilerplate_segment('LeCun is positioning AMI as something Silicon Valley cannot easily replicate for AI infrastructure development.')
print('Content retention test PASSED')
"
```

### Level 4: Thin CTA sections filtered by _MIN_SECTION_CHARS

```bash
python -c "
from ingestion.email_parser import _extract_sections

# Very thin CTA — under 100 chars after link stripping — should produce 0 sections
html_thin = '<html><body><p><a href=\"https://example.com\">Try it free today</a></p><hr/><p>Get started now!</p></body></html>'
sections = _extract_sections(html_thin)
assert len(sections) == 0, f'Expected 0 thin sections, got {len(sections)}: {sections}'
print('Thin CTA filter PASSED')

# Substantive section — over 100 chars — should survive
html_sub = '<html><body><h2>IREN Cloud AI Infrastructure</h2><p>For AI builders, time-to-compute is crucial. IREN is redefining what cloud infrastructure can do. <a href=\"https://iren.com/ai\">Learn more about IREN</a>.</p></body></html>'
sections = _extract_sections(html_sub)
assert len(sections) == 1, f'Expected 1 section, got {len(sections)}'
print('Substantive section retained PASSED')
"
```

### Level 5: Full pipeline run

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_MIN_SECTION_CHARS` is 100
- [ ] `_BOILERPLATE_SEGMENT_SIGNALS` has 13 entries
- [ ] Sponsor/advertising signals removed from `_BOILERPLATE_SEGMENT_SIGNALS`
- [ ] Podcast/media signals removed from `_BOILERPLATE_SEGMENT_SIGNALS`
- [ ] Infrastructure signals (unsubscribe, referral, legal) still present
- [ ] Full pipeline produces > 0 digest entries
- [ ] Digest output contains no headlines about subscription management, unsubscribing, or referral systems

---

## ROLLBACK CONSIDERATIONS

Both changes are isolated to two constants in `email_parser.py`. To revert: restore `_MIN_SECTION_CHARS = 50` and restore the previous 36-entry `_BOILERPLATE_SEGMENT_SIGNALS`.

## ACCEPTANCE CRITERIA

- [ ] `_MIN_SECTION_CHARS == 100`
- [ ] `len(_BOILERPLATE_SEGMENT_SIGNALS) == 13`
- [ ] Sponsor intro sections ("brought to you by IREN...") are not filtered by `_is_boilerplate_segment()`
- [ ] Infrastructure sections ("manage your subscriptions", "referral link") are filtered by `_is_boilerplate_segment()`
- [ ] Podcast/media availability sections are not filtered
- [ ] Pipeline runs end-to-end with > 0 digest entries

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _MIN_SECTION_CHARS, _BOILERPLATE_SEGMENT_SIGNALS
  assert _MIN_SECTION_CHARS == 100, f'Expected 100, got {_MIN_SECTION_CHARS}'
  assert len(_BOILERPLATE_SEGMENT_SIGNALS) == 13, f'Expected 13 signals, got {len(_BOILERPLATE_SEGMENT_SIGNALS)}'
  assert 'sponsored by' not in _BOILERPLATE_SEGMENT_SIGNALS
  assert 'brought to you by' not in _BOILERPLATE_SEGMENT_SIGNALS
  assert 'advertise to' not in _BOILERPLATE_SEGMENT_SIGNALS
  assert 'podcast episode' not in _BOILERPLATE_SEGMENT_SIGNALS
  assert 'manage your subscriptions' in _BOILERPLATE_SEGMENT_SIGNALS
  assert 'referral link' in _BOILERPLATE_SEGMENT_SIGNALS
  assert 'all rights reserved' in _BOILERPLATE_SEGMENT_SIGNALS
  print('Constants check PASSED')
  "
  ```
  Expected output or result:
  ```
  Constants check PASSED
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _is_boilerplate_segment
  assert _is_boilerplate_segment('Manage your subscriptions to our other newsletters. Unsubscribe here.')
  assert _is_boilerplate_segment('Update your email preferences or unsubscribe from this list.')
  assert _is_boilerplate_segment(\"Don't unsubscribe—just update your frequency preferences instead.\")
  assert _is_boilerplate_segment(\"You're currently a free subscriber to Import AI. Support the newsletter.\")
  assert _is_boilerplate_segment('Share your referral link below to earn free TLDR swag for your friends.')
  assert _is_boilerplate_segment('Forward this email to a friend who might enjoy it.')
  assert _is_boilerplate_segment('All rights reserved. © 2026 TechnologyAdvice, LLC. San Francisco, CA.')
  print('Infrastructure drop test PASSED')
  "
  ```
  Expected output or result:
  ```
  Infrastructure drop test PASSED
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _is_boilerplate_segment
  assert not _is_boilerplate_segment('GTC COVERAGE BROUGHT TO YOU BY IREN. For AI builders, time-to-compute is crucial. IREN is redefining cloud infrastructure.')
  assert not _is_boilerplate_segment('Sponsored by Cursor AI. Cursor is the AI code editor trusted by over 1 million developers. Write, edit, and debug code 10x faster.')
  assert not _is_boilerplate_segment('NEW REPORT: State of AI in Enterprise 2026. Download the full dataset with survey results from 2,000 engineering leaders.')
  assert not _is_boilerplate_segment('HIRING: Senior ML Engineer at Anthropic, San Francisco. Work on next-generation AI safety research. Competitive equity and salary.')
  assert not _is_boilerplate_segment('Join our live webinar on AI agent architectures, April 15 at 2pm ET. Register now to secure your spot.')
  assert not _is_boilerplate_segment('Take The Deep View with you on the go! Exclusive in-depth interviews on The Deep View: Conversations podcast every Tuesday.')
  assert not _is_boilerplate_segment('SPECIAL OFFER: 3 months of Perplexity Pro free for newsletter readers. Use code AIWEEKLY at checkout.')
  assert not _is_boilerplate_segment('LeCun is positioning AMI as something Silicon Valley cannot easily replicate for AI infrastructure development.')
  print('Content retention test PASSED')
  "
  ```
  Expected output or result:
  ```
  Content retention test PASSED
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import _extract_sections
  html_thin = '<html><body><p><a href=\"https://example.com\">Try it free today</a></p><hr/><p>Get started now!</p></body></html>'
  sections = _extract_sections(html_thin)
  assert len(sections) == 0, f'Expected 0 thin sections, got {len(sections)}: {sections}'
  print('Thin CTA filter PASSED')
  html_sub = '<html><body><h2>IREN Cloud AI Infrastructure</h2><p>For AI builders, time-to-compute is crucial. IREN is redefining what cloud infrastructure can do. <a href=\"https://iren.com/ai\">Learn more about IREN</a>.</p></body></html>'
  sections = _extract_sections(html_sub)
  assert len(sections) == 1, f'Expected 1 section, got {len(sections)}'
  print('Substantive section retained PASSED')
  "
  ```
  Expected output or result:
  ```
  Thin CTA filter PASSED
  Substantive section retained PASSED
  ```

- Item to check:
  `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Dropped|Generated|story_count|Capped)"`
  Expected output or result:
  Stage 5 generates > 0 digest entries; final JSON contains `"story_count": <N>` where N > 0.

- Item to check:
  Digest output contains no headlines about subscription management, unsubscribing, or referral systems (manual review of full pipeline JSON output)
  Expected output or result:
  No headline in the digest JSON contains "subscription", "unsubscribe", "referral", "manage preferences", or "forward this email".

---

## NOTES

- **Why remove "advertisement" and "advertorial"?** These single-word terms appeared in the signals as boilerplate guards, but they are too broad — they filter entire sections that happen to contain those words as labels. The `_MIN_SECTION_CHARS = 100` threshold handles thin ad-label-only sections.
- **Why keep "support this newsletter"?** This fires on "You're currently a free subscriber to Import AI. If you'd like to support Import AI..." — a subscription-meta/financial-ask section with no news content. It is not a sponsor product description.
- **Why not add "free swag" back?** "Free swag" was in the previous version as a referral signal. Since "referral link" is still present and referral sections universally contain "referral link", "free swag" alone is redundant and risks filtering legitimate discount/offer sections.
- **`_BOILERPLATE_ANCHOR_SUBSTRINGS` and `_BOILERPLATE_ANCHORS` are unchanged.** These filter link anchor texts (navigation, subscription, social), which remains correct behavior regardless of section classification policy.
