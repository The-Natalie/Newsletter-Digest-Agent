from __future__ import annotations

import logging

import anthropic
from anthropic import AsyncAnthropic

from config import settings
from processing.deduplicator import StoryGroup

logger = logging.getLogger(__name__)

_TOOL_NAME = "create_digest_entries"
_MAX_TOKENS = 8192
_BATCH_SIZE = 15   # ~390 tokens/entry x 15 = ~5 850 tokens; leaves headroom for verbose entries
_MAX_CHUNK_CHARS = 600

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": (
        "Return one digest entry per story group, in the same order as the input. "
        "Do not invent or modify source links — sources are provided separately."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "description": "Digest entries in the same order as the story groups.",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {
                            "type": "string",
                            "description": "Clear and direct headline, max 12 words.",
                        },
                        "summary": {
                            "type": "string",
                            "description": (
                                "2–4 sentences capturing the most complete picture "
                                "across all source versions. Prioritize clarity."
                            ),
                        },
                        "significance": {
                            "type": "string",
                            "description": (
                                "One sentence on why this matters for someone "
                                "following the given topic area."
                            ),
                        },
                    },
                    "required": ["headline", "summary", "significance"],
                },
            }
        },
        "required": ["entries"],
    },
}

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    """Lazy-initialize and cache the AsyncAnthropic client."""
    global _client
    if _client is None:
        logger.info("Initializing AsyncAnthropic client (model=%s)", settings.claude_model)
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _system_prompt(folder: str) -> str:
    return (
        f"You are generating a newsletter digest focused on {folder}. "
        "For each story group, write a concise digest entry. "
        "Be factual and direct. Do not embellish or add information not present in the sources. "
        "Produce exactly as many entries as story groups provided, in the same order."
    )


def _build_user_message(story_groups: list[StoryGroup], folder: str) -> str:
    """Build the batched multi-cluster user prompt."""
    lines: list[str] = [
        f"Below are {len(story_groups)} story group(s). "
        f"Each group contains excerpts from one or more newsletters covering the same story. "
        f"Generate one digest entry per group, in order.\n"
    ]

    for i, group in enumerate(story_groups, 1):
        lines.append(f"## Story {i}")
        for chunk in group.chunks:
            excerpt = chunk.text[:_MAX_CHUNK_CHARS]
            lines.append(f'<source newsletter="{chunk.sender}">')
            lines.append(excerpt)
            lines.append("</source>")
        lines.append("")

    lines.append(
        f"Use the `{_TOOL_NAME}` tool to return {len(story_groups)} entries "
        f"(headline, summary, significance) in the same order as the stories above. "
        f"Each significance sentence should explain why this matters for someone following {folder}."
    )
    return "\n".join(lines)


async def generate_digest(story_groups: list[StoryGroup], folder: str) -> list[dict]:
    """Call Claude to generate digest entries, batching to respect the output token ceiling.

    Splits story_groups into slices of _BATCH_SIZE and calls the Claude API once per
    slice. Results are appended to the output list in the same order as the input —
    batch 1 entries first, then batch 2, etc. — so the final list is identical in order
    and structure to what a single-call implementation would return.

    Args:
        story_groups: List of StoryGroup objects from deduplicate().
        folder: IMAP folder name used as topic context in the prompt.

    Returns:
        List of digest entry dicts, one per story group, each containing:
        {"headline": str, "summary": str, "significance": str, "sources": list[dict]}
        Returns [] if story_groups is empty.

    Raises:
        anthropic.APIError: On any Anthropic API failure. Propagates immediately;
                            entries from completed batches are discarded.
    """
    if not story_groups:
        return []

    client = _get_client()
    batches = [story_groups[i:i + _BATCH_SIZE] for i in range(0, len(story_groups), _BATCH_SIZE)]

    logger.info(
        "Calling Claude (%s) with %d story group(s) in %d batch(es) for folder '%s'",
        settings.claude_model,
        len(story_groups),
        len(batches),
        folder,
    )

    result: list[dict] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_user_message(batch, folder)

        logger.info(
            "Batch %d/%d — generating %d entries",
            batch_num,
            len(batches),
            len(batch),
        )

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=_MAX_TOKENS,
                system=_system_prompt(folder),
                messages=[{"role": "user", "content": user_message}],
                tools=[_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error("Claude API error on batch %d/%d: %s", batch_num, len(batches), exc)
            raise

        logger.debug(
            "Batch %d/%d response: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num,
            len(batches),
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        # Detect output truncation: retry by splitting the batch in half (one level only).
        # ceil-split ensures no entry is silently omitted for odd-sized batches.
        if response.stop_reason == "max_tokens":
            logger.warning(
                "Batch %d/%d truncated (stop_reason='max_tokens', %d entries requested) — "
                "retrying as two half-batches",
                batch_num,
                len(batches),
                len(batch),
            )
            split = len(batch) // 2 + len(batch) % 2  # ceiling half goes to half_a
            for half_num, half in enumerate([batch[:split], batch[split:]], 1):
                if not half:
                    continue
                half_message = _build_user_message(half, folder)
                try:
                    half_response = await client.messages.create(
                        model=settings.claude_model,
                        max_tokens=_MAX_TOKENS,
                        system=_system_prompt(folder),
                        messages=[{"role": "user", "content": half_message}],
                        tools=[_TOOL_SCHEMA],
                        tool_choice={"type": "tool", "name": _TOOL_NAME},
                    )
                except anthropic.APIError as exc:
                    logger.error(
                        "Claude API error on batch %d/%d retry-half %d: %s",
                        batch_num, len(batches), half_num, exc,
                    )
                    raise
                if half_response.stop_reason == "max_tokens":
                    logger.warning(
                        "Batch %d/%d retry-half %d also truncated — proceeding with partial output",
                        batch_num, len(batches), half_num,
                    )
                half_tool_input: dict | None = None
                for block in half_response.content:
                    if block.type == "tool_use":
                        half_tool_input = block.input
                        break
                if half_tool_input is None:
                    logger.warning(
                        "Batch %d/%d retry-half %d: no tool_use block — skipping half",
                        batch_num, len(batches), half_num,
                    )
                    continue
                half_entries: list[dict] = half_tool_input.get("entries", [])
                if len(half_entries) != len(half):
                    logger.warning(
                        "Batch %d/%d retry-half %d entry count mismatch: "
                        "Claude returned %d entries for %d story groups",
                        batch_num, len(batches), half_num, len(half_entries), len(half),
                    )
                for entry, group in zip(half_entries, half):
                    result.append({
                        "headline": entry.get("headline", ""),
                        "summary": entry.get("summary", ""),
                        "significance": entry.get("significance", ""),
                        "sources": group.sources,
                    })
            continue

        # Extract tool input from the response
        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            raise ValueError(
                f"Claude response contained no tool_use block on batch {batch_num}/{len(batches)}. "
                f"stop_reason={response.stop_reason!r}"
            )

        raw_entries: list[dict] = tool_input.get("entries", [])
        logger.info(
            "Batch %d/%d — Claude returned %d entries",
            batch_num,
            len(batches),
            len(raw_entries),
        )

        if len(raw_entries) != len(batch):
            logger.warning(
                "Batch %d/%d entry count mismatch: Claude returned %d entries for %d story groups"
                " — truncating/padding to match",
                batch_num,
                len(batches),
                len(raw_entries),
                len(batch),
            )

        # Merge Claude's text fields with pre-built source attribution from deduplicator
        for entry, group in zip(raw_entries, batch):
            result.append({
                "headline": entry.get("headline", ""),
                "summary": entry.get("summary", ""),
                "significance": entry.get("significance", ""),
                "sources": group.sources,
            })

    logger.info(
        "Stage 6/6 — Generated %d total digest entry/entries across %d batch(es)",
        len(result),
        len(batches),
    )
    return result
