from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timezone

from ai.claude_client import filter_noise, filter_stories, refine_clusters
from database import async_session, digest_runs
from ingestion.email_parser import parse_emails
from ingestion.imap_client import fetch_emails
from processing.deduplicator import deduplicate
from processing.embedder import embed_and_cluster
from config import settings

logger = logging.getLogger(__name__)

_FLAGS_PATH = "data/flags_latest.jsonl"

# ---------------------------------------------------------------------------
# Presentation-layer body normalization
# Applied to body text when building the response dict, after all pipeline
# stages, so embedding/LLM inputs are unaffected.
# ---------------------------------------------------------------------------

_BOLD_RE = re.compile(r'\*\*([^*\n]+)\*\*')          # **bold**
_BOLD_UNDER_RE = re.compile(r'__([^_\n]+)__')          # __bold__
_ITALIC_RE = re.compile(r'(?<![*\w])\*(?! )([^*\n]+?)(?<! )\*(?![*\w])')  # *italic* (no space after opening *)
_ITALIC_UNDER_RE = re.compile(r'(?<!\w)_([^_\n]+)_(?!\w)')    # _italic_


def _normalize_body(text: str) -> str:
    """Strip markdown/newsletter formatting artifacts for clean presentation.

    Transformations applied (in order):
      1. Heading markers removed:           ## Heading  → Heading
      2. Bold markers removed:              **text**    → text,  __text__ → text
      3. Italic markers removed:            *text*      → text,  _text_   → text
      4. Stray ** pairs removed (orphaned after pass 2)
      4b. Stray single _ flanked by non-word chars removed
      5. Inline bullet markers line-separated: " * item" → "\\n* item"
      6. Table separator lines removed (lines of -, |, :)
      7. Block bullet symbols removed:      ■  ▪
      8. Excess whitespace collapsed:       2+ spaces → 1, 3+ newlines → 2
    """
    # 1. Heading markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 2. Bold
    text = _BOLD_RE.sub(r'\1', text)
    text = _BOLD_UNDER_RE.sub(r'\1', text)
    # 3. Italic
    text = _ITALIC_RE.sub(r'\1', text)
    text = _ITALIC_UNDER_RE.sub(r'\1', text)
    # 4. Stray ** remaining after emphasis pass
    text = re.sub(r'\*\*', '', text)
    # 4b. Stray single _ flanked by non-word chars (e.g. `._. ` artifacts)
    text = re.sub(r'(?<!\w)_(?!\w)', '', text)
    # 5. Inline bullet markers: html2text sometimes emits `* item1 * item2` on one
    #    line. Convert each space-asterisk-space (not already at a line start) to a
    #    newline + bullet so items are individually line-separated.
    text = re.sub(r' \* ', '\n* ', text)
    # 6. Table separator lines
    text = re.sub(r'^\s*[-|:]{3,}\s*$', '', text, flags=re.MULTILINE)
    # 7. Block bullet symbols
    text = text.replace('■', '').replace('▪', '')
    # 8. Whitespace
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _normalize_title(text: str | None) -> str | None:
    """Strip formatting markers and leading decorator symbols from story titles.

    Transformations applied (in order):
      1. Bold markers removed:              **text** → text,  __text__ → text
      2. Remaining stray asterisks removed
      3. Leading non-content symbols stripped (block chars, bullets, ■ ▪ • etc.)
      4. Whitespace normalized
    Returns None if the title is empty after cleanup.
    """
    if not text:
        return None
    # 1. Bold markers
    text = _BOLD_RE.sub(r'\1', text)
    text = _BOLD_UNDER_RE.sub(r'\1', text)
    # 2. Remaining asterisks (stray * from unmatched emphasis)
    text = re.sub(r'\*+', '', text)
    # 3. Strip leading characters that are not word chars, digits, quotes, or
    #    sentence-starting punctuation. Catches ■, ▪, •, ►, →, ✔ and other
    #    Unicode block/symbol chars used as newsletter bullet decorators.
    text = re.sub(r'^[^\w\'"(]+(?=\S)', '', text)
    # 4. Normalize whitespace
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip() or None


async def build_digest(
    folder: str,
    date_start: date,
    date_end: date,
) -> dict:
    """Run the full digest pipeline end-to-end and persist the result.

    Pipeline stages:
        1. Fetch emails from IMAP
        2. Parse emails → StoryRecord list
        3. LLM noise filter → remove obvious structural non-article content
        4. Embed + cluster (threshold=settings.dedup_threshold)
        5. LLM pairwise dedup refinement → same_story/related_but_distinct/different
        6. Deduplicate → select one representative per final cluster
        7. LLM editorial filter → binary keep/drop on representatives

    Args:
        folder: IMAP folder name to read newsletters from.
        date_start: Start of the date range (inclusive).
        date_end: End of the date range (inclusive).

    Returns:
        Digest response dict with keys:
        id, generated_at, folder, date_start, date_end, story_count, stories.

    Raises:
        Exception: Any pipeline or API error. The DB row is updated to status="failed"
                   before the exception propagates to the caller.
    """
    run_id = str(uuid.uuid4())
    run_at = datetime.now(timezone.utc).replace(tzinfo=None)

    async with async_session() as session:
        await session.execute(
            digest_runs.insert().values(
                id=run_id,
                run_at=run_at,
                folder=folder,
                date_start=date_start,
                date_end=date_end,
                status="pending",
            )
        )
        await session.commit()

    logger.info("Digest run started: id=%s folder='%s' %s→%s", run_id[:8], folder, date_start, date_end)

    try:
        # ── Stage 1/7: Fetch emails ────────────────────────────────────────
        logger.info("Stage 1/7 — Fetching emails from '%s'", folder)
        raw_emails = fetch_emails(folder, date_start, date_end)
        logger.info("Stage 1/7 — Fetched %d raw email(s)", len(raw_emails))

        # ── Stage 2/7: Parse emails ───────────────────────────────────────
        logger.info("Stage 2/7 — Parsing emails into story records")
        story_records = parse_emails(raw_emails)
        logger.info("Stage 2/7 — Parsed %d story record(s)", len(story_records))

        # ── Stage 3/7: LLM noise filter ───────────────────────────────────
        logger.info("Stage 3/7 — Running LLM noise filter on %d parsed item(s)", len(story_records))
        before_noise = len(story_records)
        story_records = await filter_noise(story_records)
        noise_removed = before_noise - len(story_records)
        logger.info("Stage 3/7 — %d item(s) after noise filter (%d removed)", len(story_records), noise_removed)

        # ── Stage 4/7: Embed + cluster ────────────────────────────────────
        logger.info(
            "Stage 4/7 — Embedding and clustering (threshold=%.2f)",
            settings.dedup_threshold,
        )
        clusters = embed_and_cluster(story_records)
        logger.info("Stage 4/7 — Produced %d cluster(s)", len(clusters))

        # ── Stage 5/7: LLM pairwise dedup refinement ─────────────────────
        logger.info("Stage 5/7 — LLM pairwise dedup refinement on %d cluster(s)", len(clusters))
        clusters = await refine_clusters(clusters)
        logger.info("Stage 5/7 — %d cluster(s) after refinement", len(clusters))

        # ── Stage 6/7: Deduplicate ────────────────────────────────────────
        logger.info("Stage 6/7 — Selecting representatives from %d cluster(s)", len(clusters))
        representatives = deduplicate(clusters)
        logger.info("Stage 6/7 — %d representative(s) selected", len(representatives))

        # ── Stage 7/7: LLM editorial filter ──────────────────────────────
        logger.info("Stage 7/7 — Running LLM keep/drop filter on %d story/stories", len(representatives))
        kept, borderline_flags = await filter_stories(representatives, folder)
        dropped_count = len(representatives) - len(kept)
        logger.info(
            "Stage 7/7 — Kept %d / %d (dropped %d, borderline %d)",
            len(kept), len(representatives), dropped_count, len(borderline_flags),
        )

        # Write borderline flags file (development artifact, overwritten each run)
        os.makedirs("data", exist_ok=True)
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            for flag in borderline_flags:
                f.write(json.dumps(flag, ensure_ascii=False) + "\n")

        print(
            f"Pipeline complete: {len(kept)} kept, {dropped_count} dropped, "
            f"{len(borderline_flags)} flagged as borderline. "
            f"Flagged records written to {_FLAGS_PATH}."
        )

        # ── Build response dict ───────────────────────────────────────────
        stories = [
            {
                "title": _normalize_title(r.title),
                "body": _normalize_body(r.body),
                "link": r.links[0] if r.links else None,
                "links": r.links,
                "newsletter": r.newsletter,
                "date": r.date,
                "source_count": r.source_count,
            }
            for r in kept
        ]

        response: dict = {
            "id": run_id,
            "generated_at": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "folder": folder,
            "date_start": date_start.isoformat(),
            "date_end": date_end.isoformat(),
            "story_count": len(stories),
            "stories": stories,
        }

        async with async_session() as session:
            await session.execute(
                digest_runs.update()
                .where(digest_runs.c.id == run_id)
                .values(
                    status="complete",
                    story_count=len(stories),
                    output_json=json.dumps(response),
                )
            )
            await session.commit()

        logger.info("Digest run complete: id=%s stories=%d", run_id[:8], len(stories))
        return response

    except Exception as exc:
        logger.error("Digest run failed: id=%s error=%s", run_id[:8], exc)
        async with async_session() as session:
            await session.execute(
                digest_runs.update()
                .where(digest_runs.c.id == run_id)
                .values(status="failed", error_message=str(exc))
            )
            await session.commit()
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Generate a newsletter digest from an IMAP folder.")
    parser.add_argument("--folder", required=True, help="IMAP folder name")
    parser.add_argument("--start", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--end", required=True, metavar="YYYY-MM-DD")
    args = parser.parse_args()
    result = asyncio.run(build_digest(args.folder, date.fromisoformat(args.start), date.fromisoformat(args.end)))
    print(json.dumps(result, indent=2, ensure_ascii=False))
