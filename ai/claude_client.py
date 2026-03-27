from __future__ import annotations

import logging

import anthropic
from anthropic import AsyncAnthropic

from config import settings
from processing.deduplicator import StoryGroup

logger = logging.getLogger(__name__)

_TOOL_NAME = "create_digest_entries"
_MAX_TOKENS = 8192
_MAX_CHUNK_CHARS = 600
_MAX_STORY_GROUPS = 50   # max groups per Claude call; keeps output within _MAX_TOKENS

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
    """Call Claude to generate digest entries for all story groups in one API call.

    Args:
        story_groups: List of StoryGroup objects from deduplicate().
        folder: IMAP folder name used as topic context in the prompt.

    Returns:
        List of digest entry dicts, one per story group, each containing:
        {"headline": str, "summary": str, "significance": str, "sources": list[dict]}
        Returns [] if story_groups is empty.

    Raises:
        anthropic.APIError: On any Anthropic API failure. Let callers handle retries.
    """
    if not story_groups:
        return []

    # Sort by source count descending (most cross-covered stories first), then cap.
    # This prioritises multi-newsletter coverage and keeps output within _MAX_TOKENS.
    if len(story_groups) > _MAX_STORY_GROUPS:
        total_available = len(story_groups)
        story_groups = sorted(story_groups, key=lambda g: len(g.sources), reverse=True)
        story_groups = story_groups[:_MAX_STORY_GROUPS]
        logger.info(
            "Capped story groups to top %d by source count (%d total available)",
            _MAX_STORY_GROUPS,
            total_available,
        )

    client = _get_client()
    user_message = _build_user_message(story_groups, folder)

    logger.info(
        "Calling Claude (%s) with %d story group(s) for folder '%s'",
        settings.claude_model,
        len(story_groups),
        folder,
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
        logger.error("Claude API error: %s", exc)
        raise

    logger.debug(
        "Claude response: stop_reason=%r  input_tokens=%d  output_tokens=%d",
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    # Extract tool input from the response
    tool_input: dict | None = None
    for block in response.content:
        if block.type == "tool_use":
            tool_input = block.input
            break

    if tool_input is None:
        raise ValueError(
            f"Claude response contained no tool_use block. "
            f"stop_reason={response.stop_reason!r}"
        )

    raw_entries: list[dict] = tool_input.get("entries", [])
    logger.info("Claude returned %d digest entry/entries", len(raw_entries))

    if len(raw_entries) != len(story_groups):
        logger.warning(
            "Entry count mismatch: Claude returned %d entries for %d story groups — "
            "truncating/padding to match",
            len(raw_entries),
            len(story_groups),
        )

    # Merge Claude's text fields with pre-built source attribution from deduplicator
    result: list[dict] = []
    for entry, group in zip(raw_entries, story_groups):
        result.append({
            "headline": entry.get("headline", ""),
            "summary": entry.get("summary", ""),
            "significance": entry.get("significance", ""),
            "sources": group.sources,
        })

    return result
