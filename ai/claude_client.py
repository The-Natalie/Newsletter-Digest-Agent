from __future__ import annotations

import logging
from collections import defaultdict

import anthropic
from anthropic import AsyncAnthropic

from config import settings
from ingestion.email_parser import StoryRecord

logger = logging.getLogger(__name__)

# ── Shared client ──────────────────────────────────────────────────────────────

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    """Lazy-initialize and cache the AsyncAnthropic client."""
    global _client
    if _client is None:
        logger.info("Initializing AsyncAnthropic client (model=%s)", settings.claude_model)
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


# ── filter_noise ───────────────────────────────────────────────────────────────

_NOISE_TOOL_NAME = "filter_noise"
_NOISE_BATCH_SIZE = 30
_NOISE_MAX_BODY_CHARS = 300

_NOISE_TOOL_SCHEMA: dict = {
    "name": _NOISE_TOOL_NAME,
    "description": (
        "Classify each item as ARTICLE or NOISE. "
        "Only mark as NOISE when the item is clearly non-article structural content. "
        "When uncertain, classify as ARTICLE."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per item, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "is_noise": {
                            "type": "boolean",
                            "description": (
                                "True = NOISE (remove). False = ARTICLE (keep). "
                                "Default to False when uncertain."
                            ),
                        },
                    },
                    "required": ["is_noise"],
                },
            }
        },
        "required": ["decisions"],
    },
}

_NOISE_SYSTEM_PROMPT = (
    "You are a pre-processing filter for a newsletter digest pipeline. "
    "Your only job is to remove obvious structural noise before content analysis.\n\n"
    "Mark is_noise=True ONLY for items that clearly contain no article or news content:\n"
    "- Sponsor or referral blocks that are purely promotional: "
    "taglines, brand-awareness copy, buzzword-heavy ad text with no specific facts "
    "(\u2018AI-powered. Enterprise-grade. Transform your workflow.\u2019). "
    "NOT the same as sponsor content that explains a specific product or offer \u2014 see KEEP rules.\n"
    "- Newsletter infrastructure: subscribe/unsubscribe prompts, account management, "
    "referral incentive programs (\u2018Refer 3 friends to unlock...\u2019)\n"
    "- Session blurbs and agenda items: conference schedule entries, panel descriptions, "
    "event time/location notices with no substantive news content "
    "(\u2018Join us Thursday at 2pm for a discussion on AI safety\u2019)\n"
    "- Tool-tip and feature-callout marketing: product pitches framed as tips "
    "(\u2018Did you know you can use X to do Y?\u2019) with no real news or factual content\n"
    "- Pure CTAs with no substantive content: \u2018Click here\u2019, \u2018Sign up today\u2019, "
    "\u2018Get started free\u2019 \u2014 where the entire item is the CTA with nothing else\n"
    "- Newsletter intro/outro shells: \u2018Welcome to today\u2019s issue\u2019, "
    "\u2018That\u2019s all for this week\u2019, editor\u2019s notes with no article content\n"
    "- Polls and surveys: \u2018How did we do? Vote below\u2019, reader feedback requests\n\n"
    "Mark is_noise=False (KEEP) for everything else, including:\n"
    "- Any real article, news item, announcement, or report \u2014 even if short or low quality\n"
    "- Sponsor content that provides specific, usable facts: a named product with a concrete "
    "capability, a specific offer or discount, a date-bound event, or a factual explanation "
    "a reader could act on. The test: does this item give the reader specific information "
    "they could use? If yes, keep it.\n"
    "- Job listings, product launches, research summaries, tool releases, event notices\n"
    "- Any item that is ambiguous \u2014 when in doubt, always keep\n\n"
    "This filter is maximally conservative. It is better to keep 10 noisy items "
    "than to accidentally remove one real article."
)


def _build_noise_message(stories: list[StoryRecord]) -> str:
    lines: list[str] = [
        f"Below are {len(stories)} item(s) extracted from newsletters. "
        "Classify each as ARTICLE or NOISE.\n"
    ]
    for i, story in enumerate(stories, 1):
        lines.append(f"## Item {i}")
        if story.title:
            lines.append(f"Title: {story.title}")
        lines.append(f"Newsletter: {story.newsletter}")
        lines.append(f"Body: {story.body[:_NOISE_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_NOISE_TOOL_NAME}` tool to return {len(stories)} decisions "
        f"(is_noise) in the same order."
    )
    return "\n".join(lines)


async def filter_noise(stories: list[StoryRecord]) -> list[StoryRecord]:
    """Pre-cluster noise filter. Removes obvious structural non-article content.

    Runs before embedding. Maximally conservative — only removes items that are
    unambiguously structural noise (sponsor blocks, referral prompts, intro/outro
    shells, polls, subscription text). Never removes real articles, even if short.

    Args:
        stories: All StoryRecord objects from parse_emails().

    Returns:
        Filtered list. On API failure, returns input list unchanged (fail-open).
    """
    if not stories:
        return []

    client = _get_client()
    batches = [stories[i:i + _NOISE_BATCH_SIZE] for i in range(0, len(stories), _NOISE_BATCH_SIZE)]

    logger.info(
        "LLM noise filter: %d item(s) in %d batch(es)",
        len(stories),
        len(batches),
    )

    kept: list[StoryRecord] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_noise_message(batch)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                system=_NOISE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[_NOISE_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _NOISE_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error(
                "LLM noise filter API error on batch %d/%d: %s — keeping all",
                batch_num, len(batches), exc,
            )
            kept.extend(batch)
            continue

        logger.debug(
            "LLM noise filter batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning(
                "LLM noise filter batch %d/%d: no tool_use block — keeping all %d",
                batch_num, len(batches), len(batch),
            )
            kept.extend(batch)
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM noise filter batch %d/%d: count mismatch (%d decisions for %d items) — keeping all",
                batch_num, len(batches), len(decisions), len(batch),
            )
            kept.extend(batch)
            continue

        batch_kept = 0
        batch_removed = 0
        for story, decision in zip(batch, decisions):
            if not decision.get("is_noise", False):
                kept.append(story)
                batch_kept += 1
            else:
                batch_removed += 1

        logger.info(
            "LLM noise filter batch %d/%d: kept %d / %d (removed %d as noise)",
            batch_num, len(batches), batch_kept, len(batch), batch_removed,
        )

    return kept


# ── refine_clusters ────────────────────────────────────────────────────────────

_REFINE_TOOL_NAME = "refine_clusters"
_REFINE_BATCH_SIZE = 20
_REFINE_MAX_BODY_CHARS = 350

_REFINE_TOOL_SCHEMA: dict = {
    "name": _REFINE_TOOL_NAME,
    "description": (
        "For each story pair, classify the relationship between the two stories. "
        "Return one decision per pair, in input order."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per pair, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "relationship": {
                            "type": "string",
                            "enum": ["same_story", "related_but_distinct", "different"],
                            "description": (
                                "'same_story': both stories cover the same specific event, "
                                "announcement, or development \u2014 merge them. "
                                "'related_but_distinct': same company/topic but different "
                                "developments or announcements \u2014 keep separate. "
                                "'different': unrelated stories \u2014 keep separate."
                            ),
                        },
                    },
                    "required": ["relationship"],
                },
            }
        },
        "required": ["decisions"],
    },
}

_REFINE_SYSTEM_PROMPT = (
    "You are a deduplication assistant for a newsletter digest. "
    "You will be shown pairs of story excerpts from different newsletters that "
    "scored above the embedding similarity threshold.\n\n"
    "For each pair, classify the relationship:\n\n"
    "'same_story' \u2014 Both stories are specifically reporting on the SAME single "
    "announcement, product release, or event. The underlying news item is identical "
    "even if the writing style, length, or framing differs. "
    "Example: TLDR says 'OpenAI released GPT-5 today' and The Deep View says "
    "'OpenAI unveils GPT-5 with enhanced reasoning' \u2014 same story.\n\n"
    "'related_but_distinct' \u2014 The stories share context (same company, same conference, "
    "same day, same broad topic) but cover DIFFERENT specific developments or announcements. "
    "Each story contains information not present in the other. "
    "Examples:\n"
    "- A broad conference recap covering multiple announcements vs. a story focused on one "
    "specific announcement from that same conference \u2014 related_but_distinct.\n"
    "- Two stories from the same company at the same conference: one covers their robotics "
    "platform launch, another covers their inference chip performance \u2014 related_but_distinct.\n"
    "- One story covers the keynote highlights across several topics; another covers one "
    "specific product announcement from that keynote \u2014 related_but_distinct.\n\n"
    "'different' \u2014 The stories are about unrelated topics.\n\n"
    "Critical rule: Same company + same conference + same day does NOT make stories the same. "
    "Ask: are both stories reporting on the exact same single announcement? "
    "If each story contains developments or details not in the other, they are related_but_distinct.\n\n"
    "When in doubt, use 'related_but_distinct' or 'different'. "
    "Only use 'same_story' when you are confident both stories are covering the same specific event. "
    "It is better to show a near-duplicate than to hide a distinct story."
)


def _build_refine_message(pairs: list[tuple[StoryRecord, StoryRecord]]) -> str:
    lines: list[str] = [
        f"Below are {len(pairs)} story pair(s) from different newsletters. "
        "Classify the relationship between the stories in each pair.\n"
    ]
    for i, (story_a, story_b) in enumerate(pairs, 1):
        lines.append(f"## Pair {i}")
        lines.append(f"Story A (from {story_a.newsletter}):")
        if story_a.title:
            lines.append(f"  Title: {story_a.title}")
        lines.append(f"  Body: {story_a.body[:_REFINE_MAX_BODY_CHARS]}")
        lines.append(f"Story B (from {story_b.newsletter}):")
        if story_b.title:
            lines.append(f"  Title: {story_b.title}")
        lines.append(f"  Body: {story_b.body[:_REFINE_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_REFINE_TOOL_NAME}` tool to return {len(pairs)} decisions "
        "(relationship: same_story | related_but_distinct | different) in the same order."
    )
    return "\n".join(lines)


async def refine_clusters(
    clusters: list[list[StoryRecord]],
) -> list[list[StoryRecord]]:
    """LLM pairwise dedup refinement within each candidate cluster.

    For each cluster with more than one story, generates all pairwise comparisons
    and asks the LLM to classify each pair as same_story, related_but_distinct,
    or different. Only same_story pairs are merged (via union-find). Clusters that
    contained only related or different stories are split into singletons.

    Args:
        clusters: Candidate clusters from embed_and_cluster(). Singletons pass through.

    Returns:
        Refined cluster list. Same_story groups become single clusters; unconfirmed
        stories are returned as singletons. On API failure or count mismatch, the
        input clusters are returned unchanged (fail-open: trust embedding result).
    """
    if not clusters:
        return []

    # Collect all pairwise comparisons across multi-story clusters
    all_pairs: list[tuple[StoryRecord, StoryRecord]] = []
    pair_origins: list[tuple[int, int, int]] = []  # (cluster_idx, story_i, story_j)

    for c_idx, cluster in enumerate(clusters):
        if len(cluster) < 2:
            continue
        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                all_pairs.append((cluster[i], cluster[j]))
                pair_origins.append((c_idx, i, j))

    if not all_pairs:
        return clusters[:]

    client = _get_client()
    batches = [all_pairs[k:k + _REFINE_BATCH_SIZE] for k in range(0, len(all_pairs), _REFINE_BATCH_SIZE)]

    logger.info(
        "LLM cluster refinement: %d pair(s) across %d multi-story cluster(s) in %d batch(es)",
        len(all_pairs),
        sum(1 for c in clusters if len(c) >= 2),
        len(batches),
    )

    # Collect LLM decisions; None = not yet decided (API failure fallback)
    pair_decisions: list[str | None] = [None] * len(all_pairs)
    pair_offset = 0

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_refine_message(batch)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                system=_REFINE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[_REFINE_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _REFINE_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error(
                "LLM cluster refinement API error on batch %d/%d: %s — keeping clusters unchanged",
                batch_num, len(batches), exc,
            )
            pair_offset += len(batch)
            continue

        logger.debug(
            "LLM cluster refinement batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning(
                "LLM cluster refinement batch %d/%d: no tool_use block — keeping clusters unchanged",
                batch_num, len(batches),
            )
            pair_offset += len(batch)
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM cluster refinement batch %d/%d: count mismatch (%d decisions for %d pairs) — keeping clusters unchanged",
                batch_num, len(batches), len(decisions), len(batch),
            )
            pair_offset += len(batch)
            continue

        batch_same = 0
        for k, decision in enumerate(decisions):
            rel = decision.get("relationship", "different")
            pair_decisions[pair_offset + k] = rel
            if rel == "same_story":
                batch_same += 1

        logger.info(
            "LLM cluster refinement batch %d/%d: %d/%d pairs classified as same_story",
            batch_num, len(batches), batch_same, len(batch),
        )
        pair_offset += len(batch)

    # Apply union-find per cluster based on same_story decisions
    cluster_same_pairs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for pair_idx, (c_idx, i, j) in enumerate(pair_origins):
        if pair_decisions[pair_idx] == "same_story":
            cluster_same_pairs[c_idx].append((i, j))

    # Track clusters with undecided pairs (API failure) — keep those intact
    cluster_had_failure: set[int] = set()
    for pair_idx, (c_idx, i, j) in enumerate(pair_origins):
        if pair_decisions[pair_idx] is None:
            cluster_had_failure.add(c_idx)

    result: list[list[StoryRecord]] = []

    for c_idx, cluster in enumerate(clusters):
        if len(cluster) < 2:
            result.append(cluster)
            continue

        if c_idx in cluster_had_failure:
            result.append(cluster)
            continue

        # Union-find within this cluster
        n = len(cluster)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i, j in cluster_same_pairs[c_idx]:
            union(i, j)

        # Group stories by root
        groups: dict[int, list[StoryRecord]] = defaultdict(list)
        for story_idx, story in enumerate(cluster):
            groups[find(story_idx)].append(story)

        for sub_cluster in groups.values():
            result.append(sub_cluster)

    same_count = sum(len(v) for v in cluster_same_pairs.values())
    logger.info(
        "LLM cluster refinement: %d same_story pair(s) confirmed → %d cluster(s) (was %d)",
        same_count,
        len(result),
        len(clusters),
    )
    return result


# ── filter_stories ─────────────────────────────────────────────────────────────

_FILTER_TOOL_NAME = "filter_stories"
_FILTER_BATCH_SIZE = 25
_FILTER_MAX_BODY_CHARS = 300

_FILTER_TOOL_SCHEMA: dict = {
    "name": _FILTER_TOOL_NAME,
    "description": (
        "Classify each story as KEEP or DROP. "
        "Return one decision per story, in the same order as the input."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per story, in input order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "keep": {
                            "type": "boolean",
                            "description": "True = KEEP, False = DROP.",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "borderline"],
                            "description": "Use 'borderline' when uncertain.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One sentence explaining the decision. Required when confidence is 'borderline'.",
                        },
                    },
                    "required": ["keep", "confidence", "reasoning"],
                },
            }
        },
        "required": ["decisions"],
    },
}


def _filter_system_prompt(folder: str) -> str:
    return (
        f"You are a content filter for a newsletter digest focused on {folder}.\n\n"
        "Classify each story as KEEP or DROP.\n\n"
        "KEEP if the item contains:\n"
        "- A real news story, article, or announcement\n"
        "- A product launch, tool release, research paper, or report\n"
        "- A job listing or career opportunity\n"
        "- Sponsor content that includes a concrete offer, discount, free tool, "
        "webinar, or substantive explanation with real value to the reader\n\n"
        "DROP if the item contains only:\n"
        "- Newsletter housekeeping (subscription management, unsubscribe prompts)\n"
        "- Audience growth content: 'advertise with us', referral programs, "
        "generic brand-awareness blurbs with no real content\n"
        "- Legal / footer boilerplate (terms, privacy policy, all rights reserved)\n"
        "- Reader feedback requests (surveys, polls, 'share your thoughts')\n"
        "- Editorial shell content with no actual information (intros, outros, "
        "'that's all for this week')\n"
        "- Pure call-to-action blocks with no substantive content beyond the CTA itself\n\n"
        "When in doubt, KEEP. Only DROP on clear non-story signals. "
        "Never drop short valid stories — a one-sentence item with a link is valid."
    )


def _build_filter_message(stories: list[StoryRecord], folder: str) -> str:
    lines: list[str] = [
        f"Below are {len(stories)} story item(s) from newsletters about {folder}.\n"
    ]
    for i, story in enumerate(stories, 1):
        lines.append(f"## Story {i}")
        if story.title:
            lines.append(f"Title: {story.title}")
        lines.append(f"Newsletter: {story.newsletter}")
        lines.append(f"Body: {story.body[:_FILTER_MAX_BODY_CHARS]}")
        lines.append("")
    lines.append(
        f"Use the `{_FILTER_TOOL_NAME}` tool to return {len(stories)} decisions "
        f"(keep, confidence, reasoning) in the same order."
    )
    return "\n".join(lines)


async def filter_stories(
    stories: list[StoryRecord],
    folder: str,
) -> tuple[list[StoryRecord], list[dict]]:
    """Binary KEEP/DROP filter for deduplicated story items.

    Args:
        stories: List of StoryRecord objects after deduplication.
        folder: IMAP folder name used as topic context.

    Returns:
        Tuple of (kept, borderline_flags) where:
        - kept: StoryRecord objects the LLM decided to KEEP
        - borderline_flags: List of dicts for flags_latest.jsonl,
          one per item with confidence='borderline'

    On API failure, returns (stories, []) — fail-open: keep all, no flags.
    """
    if not stories:
        return [], []

    client = _get_client()
    batches = [stories[i:i + _FILTER_BATCH_SIZE] for i in range(0, len(stories), _FILTER_BATCH_SIZE)]

    logger.info(
        "LLM filter: %d story/stories in %d batch(es) for folder '%s'",
        len(stories),
        len(batches),
        folder,
    )

    kept: list[StoryRecord] = []
    borderline_flags: list[dict] = []

    for batch_num, batch in enumerate(batches, 1):
        user_message = _build_filter_message(batch, folder)

        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=1024,
                system=_filter_system_prompt(folder),
                messages=[{"role": "user", "content": user_message}],
                tools=[_FILTER_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _FILTER_TOOL_NAME},
            )
        except anthropic.APIError as exc:
            logger.error("LLM filter API error on batch %d/%d: %s — keeping all", batch_num, len(batches), exc)
            kept.extend(batch)
            continue

        logger.debug(
            "LLM filter batch %d/%d: stop_reason=%r  input_tokens=%d  output_tokens=%d",
            batch_num, len(batches), response.stop_reason,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        tool_input: dict | None = None
        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                break

        if tool_input is None:
            logger.warning("LLM filter batch %d/%d: no tool_use block — keeping all %d", batch_num, len(batches), len(batch))
            kept.extend(batch)
            continue

        decisions: list[dict] = tool_input.get("decisions", [])
        if len(decisions) != len(batch):
            logger.warning(
                "LLM filter batch %d/%d: count mismatch (%d decisions for %d stories) — keeping all",
                batch_num, len(batches), len(decisions), len(batch),
            )
            kept.extend(batch)
            continue

        batch_kept = 0
        batch_dropped = 0
        for story, decision in zip(batch, decisions):
            keep = decision.get("keep", True)
            confidence = decision.get("confidence", "high")
            reasoning = decision.get("reasoning", "")
            if keep:
                kept.append(story)
                batch_kept += 1
            else:
                batch_dropped += 1
            if confidence == "borderline":
                borderline_flags.append({
                    "decision": "KEEP" if keep else "DROP",
                    "confidence": "borderline",
                    "llm_reasoning": reasoning,
                    "item": {
                        "title": story.title,
                        "body": story.body,
                        "link": story.links[0] if story.links else None,
                        "newsletter": story.newsletter,
                        "date": story.date,
                    },
                })

        logger.info(
            "LLM filter batch %d/%d: kept %d / %d (dropped %d)",
            batch_num, len(batches), batch_kept, len(batch), batch_dropped,
        )

    return kept, borderline_flags
