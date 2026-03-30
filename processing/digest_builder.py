from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa

from ai.claude_client import generate_digest
from ai.story_reviewer import review_story_groups
from database import async_session, digest_runs
from ingestion.email_parser import parse_emails
from ingestion.imap_client import fetch_emails
from processing.deduplicator import deduplicate
from processing.embedder import embed_and_cluster

logger = logging.getLogger(__name__)

_MAX_STORY_GROUPS = 50  # MVP cap: applied after AI review, before generation (Phase 2: replace with batching)


async def build_digest(
    folder: str,
    date_start: date,
    date_end: date,
) -> dict:
    """Run the full digest pipeline end-to-end and persist the result.

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

    # ── Insert pending row ──────────────────────────────────────────────────
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

    logger.info(
        "Digest run started: id=%s folder='%s' %s→%s",
        run_id[:8],
        folder,
        date_start,
        date_end,
    )

    try:
        # ── Stage 1: Fetch emails ──────────────────────────────────────────
        logger.info("Stage 1/6 — Fetching emails from '%s'", folder)
        raw_emails = fetch_emails(folder, date_start, date_end)
        logger.info("Stage 1/6 — Fetched %d raw email(s)", len(raw_emails))

        # ── Stage 2: Parse emails ─────────────────────────────────────────
        logger.info("Stage 2/6 — Parsing emails")
        parsed_emails = parse_emails(raw_emails)
        logger.info("Stage 2/6 — Parsed %d email(s)", len(parsed_emails))

        # ── Stage 3: Embed and cluster ────────────────────────────────────
        logger.info("Stage 3/6 — Embedding and clustering story chunks")
        clusters = embed_and_cluster(parsed_emails)
        logger.info("Stage 3/6 — Produced %d cluster(s)", len(clusters))

        # ── Stage 4: Deduplicate ──────────────────────────────────────────
        logger.info("Stage 4/6 — Deduplicating clusters into story groups")
        story_groups = deduplicate(clusters)
        logger.info("Stage 4/6 — Produced %d story group(s)", len(story_groups))

        # ── Stage 5: AI review ────────────────────────────────────────────
        logger.info("Stage 5/6 — Running AI review to filter non-story groups")
        try:
            reviewed_groups = await review_story_groups(story_groups, folder)
        except Exception as exc:
            logger.warning(
                "AI review failed (%s) — continuing with all %d group(s) unfiltered",
                exc,
                len(story_groups),
            )
            reviewed_groups = story_groups
        logger.info(
            "Stage 5/6 — Review complete: %d group(s) kept (dropped %d)",
            len(reviewed_groups),
            len(story_groups) - len(reviewed_groups),
        )

        # Apply MVP cap after review (temporary constraint; Phase 2 replaces with batching)
        if len(reviewed_groups) > _MAX_STORY_GROUPS:
            logger.info(
                "Capping story groups: %d → %d (MVP limit; Phase 2 will batch instead)",
                len(reviewed_groups),
                _MAX_STORY_GROUPS,
            )
            reviewed_groups = reviewed_groups[:_MAX_STORY_GROUPS]

        # ── Stage 6: AI generation ────────────────────────────────────────
        logger.info("Stage 6/6 — Generating digest entries via Claude")
        stories = await generate_digest(reviewed_groups, folder)
        logger.info("Stage 6/6 — Generated %d digest entry/entries", len(stories))

        # ── Build response dict ───────────────────────────────────────────
        response: dict = {
            "id": run_id,
            "generated_at": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "folder": folder,
            "date_start": date_start.isoformat(),
            "date_end": date_end.isoformat(),
            "story_count": len(stories),
            "stories": stories,
        }

        # ── Update DB: complete ───────────────────────────────────────────
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

        logger.info(
            "Digest run complete: id=%s stories=%d",
            run_id[:8],
            len(stories),
        )
        return response

    except Exception as exc:
        # ── Update DB: failed ─────────────────────────────────────────────
        logger.error("Digest run failed: id=%s error=%s", run_id[:8], exc)
        async with async_session() as session:
            await session.execute(
                digest_runs.update()
                .where(digest_runs.c.id == run_id)
                .values(
                    status="failed",
                    error_message=str(exc),
                )
            )
            await session.commit()
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Generate a newsletter digest from an IMAP folder."
    )
    parser.add_argument("--folder", required=True, help="IMAP folder name")
    parser.add_argument("--start", required=True, metavar="YYYY-MM-DD", help="Start date (inclusive)")
    parser.add_argument("--end", required=True, metavar="YYYY-MM-DD", help="End date (inclusive)")
    args = parser.parse_args()

    date_start = date.fromisoformat(args.start)
    date_end = date.fromisoformat(args.end)

    result = asyncio.run(build_digest(args.folder, date_start, date_end))
    print(json.dumps(result, indent=2, ensure_ascii=False))
