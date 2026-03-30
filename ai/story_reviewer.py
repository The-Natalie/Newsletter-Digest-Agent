from __future__ import annotations

import logging

import anthropic
from anthropic import AsyncAnthropic

from config import settings
from processing.deduplicator import StoryGroup

logger = logging.getLogger(__name__)

_TOOL_NAME = "classify_story_groups"
_MAX_TOKENS = 1024          # decisions are short strings; 1024 is more than enough
_MAX_CHUNK_CHARS = 300      # show less text than generation — enough to classify
_MAX_REVIEW_GROUPS = 100    # MVP safety cap on reviewer input
_REVIEWER_BATCH_SIZE = 25   # 25 groups × ~3 tokens/decision = ~75 tokens; well under 1024 ceiling

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": (
        "Classify each story group as KEEP or DROP. "
        "Return one decision per group, in the same order as the input."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per story group, in input order.",
                "items": {
                    "type": "string",
                    "enum": ["KEEP", "DROP"],
                },
            }
        },
        "required": ["decisions"],
    },
}

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    """Lazy-initialize and cache the AsyncAnthropic client."""
    global _client
    if _client is None:
        logger.info("Initializing AsyncAnthropic client for reviewer (model=%s)", settings.claude_model)
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _system_prompt(folder: str) -> str:
    return (
        f"You are a content filter for a newsletter digest focused on {folder}.\n\n"
        "Your job is to classify each story group as KEEP or DROP.\n\n"
        "KEEP if the group contains:\n"
        "- A real news story, article, or announcement\n"
        "- A product launch, tool release, research paper, or report\n"
        "- A job listing or career opportunity\n"
        "- Sponsor or partner content that includes a concrete offer, discount, free tool, "
        "webinar, report, or substantive explanation — any sponsor section with real "
        "informational content for the reader\n\n"
        "DROP if the group contains only:\n"
        "- Newsletter housekeeping (subscription management, preferences, unsubscribe prompts)\n"
        "- Audience growth content: \"advertise with us,\" sponsorship sales copy, referral "
        "programs, or generic brand-awareness blurbs with no real content\n"
        "- Legal / footer boilerplate (terms of service, privacy policy, all rights reserved)\n"
        "- Reader feedback requests (surveys, polls, \"share your thoughts\")\n"
        "- Editorial shell content with no actual information (intros, outros, "
        "\"that's all for this week\")\n"
        "- Pure call-to-action blocks with no substantive content beyond the CTA itself\n\n"
        "When in doubt, KEEP. Only DROP on clear non-story signals."
    )


def _build_review_message(story_groups: list[StoryGroup], folder: str) -> str:
    """Build the batched review prompt."""
    lines: list[str] = [
        f"Below are {len(story_groups)} story group(s) from newsletters about {folder}.\n"
    ]

    for i, group in enumerate(story_groups, 1):
        lines.append(f"## Group {i}")
        for chunk in group.chunks:
            lines.append(f'<source newsletter="{chunk.sender}">{chunk.text[:_MAX_CHUNK_CHARS]}</source>')
        lines.append("")

    lines.append(
        f"Use the {_TOOL_NAME!r} tool to return {len(story_groups)} decisions "
        f"(KEEP or DROP) in the same order."
    )
    return "\n".join(lines)


async def review_story_groups(story_groups: list[StoryGroup], folder: str) -> list[StoryGroup]:
    """Classify story groups as KEEP or DROP before digest generation.

    Splits capped_groups into slices of _REVIEWER_BATCH_SIZE and calls the Claude API
    once per slice. Decisions are merged in input order, so the filtered result is
    identical to what a single-call implementation would return.

    Each batch fails open independently: if a batch returns a count mismatch or no
    tool_use block, all groups in that batch are kept (not dropped).

    Args:
        story_groups: List of StoryGroup objects from deduplicate().
        folder: IMAP folder name used as topic context in the prompt.

    Returns:
        Filtered list containing only KEEP groups. Returns all groups unfiltered
        if the reviewer call fails or returns malformed output (fail-open).
        Returns [] immediately if story_groups is empty.

    Raises:
        anthropic.APIError: Propagates to the caller (digest_builder.py Stage 5
                            try/except), which handles it with fail-open behavior.
    """
    if not story_groups:
        return []

    # Apply reviewer input cap
    capped_groups = story_groups
    if len(story_groups) > _MAX_REVIEW_GROUPS:
        logger.warning(
            "Reviewer input cap: %d groups exceeds limit of %d — reviewing first %d only",
            len(story_groups),
            _MAX_REVIEW_GROUPS,
            _MAX_REVIEW_GROUPS,
        )
        capped_groups = story_groups[:_MAX_REVIEW_GROUPS]

    client = _get_client()
    batches = [capped_groups[i:i + _REVIEWER_BATCH_SIZE] for i in range(0, len(capped_groups), _REVIEWER_BATCH_SIZE)]

    logger.info(
        "Reviewing %d story group(s) in %d batch(es) for folder '%s'",
        len(capped_groups),
        len(batches),
        folder,
    )

    kept: list[StoryGroup] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_review_message(batch, folder)

        logger.info(
            "Reviewer batch %d/%d — classifying %d group(s)",
            batch_num,
            len(batches),
            len(batch),
        )

        # anthropic.APIError is intentionally NOT caught here — propagates to digest_builder.py
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=_MAX_TOKENS,
            system=_system_prompt(folder),
            messages=[{"role": "user", "content": user_message}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        logger.debug(
            "Reviewer batch %d/%d response: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num,
            len(batches),
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        # Extract tool input — fail-open on malformed output
        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning(
                "Reviewer batch %d/%d: no tool_use block (stop_reason=%r) — keeping all %d group(s)",
                batch_num,
                len(batches),
                response.stop_reason,
                len(batch),
            )
            kept.extend(batch)
            continue

        decisions: list[str] = tool_input.get("decisions", [])

        if len(decisions) != len(batch):
            logger.warning(
                "Reviewer batch %d/%d: decision count mismatch: got %d decisions for %d groups — keeping all",
                batch_num,
                len(batches),
                len(decisions),
                len(batch),
            )
            kept.extend(batch)
            continue

        batch_kept = [group for group, decision in zip(batch, decisions) if decision == "KEEP"]
        batch_dropped = len(batch) - len(batch_kept)
        logger.info(
            "Reviewer batch %d/%d: kept %d / %d (dropped %d)",
            batch_num,
            len(batches),
            len(batch_kept),
            len(batch),
            batch_dropped,
        )
        kept.extend(batch_kept)

    total_dropped = len(capped_groups) - len(kept)
    logger.info(
        "Review complete: kept %d / %d group(s) (dropped %d) across %d batch(es)",
        len(kept),
        len(capped_groups),
        total_dropped,
        len(batches),
    )
    return kept
