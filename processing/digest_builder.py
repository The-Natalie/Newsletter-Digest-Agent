from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
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
                "title": r.title,
                "body": r.body,
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
