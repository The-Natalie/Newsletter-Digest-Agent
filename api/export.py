from __future__ import annotations

import html as _html
import json
import logging
from io import BytesIO

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from database import async_session, digest_runs

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_html(data: dict) -> str:
    """Build a self-contained HTML string from a digest dict (for weasyprint)."""
    folder = data.get("folder", "")
    date_start = data.get("date_start", "")
    date_end = data.get("date_end", "")
    stories = data.get("stories", [])

    story_blocks = []
    for story in stories:
        title = story.get("title") or "(untitled)"
        body = story.get("body", "")
        newsletter = story.get("newsletter", "")
        date = story.get("date", "")

        links: list[str] = list(story.get("links") or [])
        single_link = story.get("link")
        if single_link and single_link not in links:
            links.insert(0, single_link)

        resources_html = ""
        if links:
            items = "".join(
                f'<li><a href="{_html.escape(url)}">Link {j}</a></li>'
                for j, url in enumerate(links[:5], 1)
            )
            resources_html = (
                f'<p class="res-label">Resources:</p>'
                f'<ul class="resources">{items}</ul>'
            )

        story_blocks.append(
            f"""<div class="story">
  <h2>{_html.escape(title)}</h2>
  <p class="meta">{_html.escape(newsletter)} &middot; {date}</p>
  <p class="body">{_html.escape(body)}</p>
  {resources_html}
</div>"""
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Digest &mdash; {_html.escape(folder)}</title>
<style>
  body {{ font-family: Georgia, serif; font-size: 12pt; margin: 2cm; color: #111; }}
  h1 {{ font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 6pt; margin-bottom: 4pt; }}
  h2 {{ font-size: 13pt; margin-top: 0; margin-bottom: 3pt; font-family: Helvetica, sans-serif; }}
  .meta {{ font-size: 9pt; color: #888; margin: 0 0 8pt 0; }}
  .body {{ line-height: 1.6; font-size: 11pt; margin-bottom: 6pt; }}
  .res-label {{ font-size: 9pt; color: #888; margin: 6pt 0 3pt 0; }}
  .resources {{ margin: 0; padding-left: 16pt; font-size: 9pt; }}
  .resources a {{ color: #0066cc; text-decoration: none; }}
  .story {{ margin-bottom: 0; border-top: 1px solid #ddd; padding-top: 14pt; margin-top: 14pt; }}
  .story:first-child {{ border-top: none; padding-top: 0; margin-top: 0; }}
</style>
</head>
<body>
<h1>Newsletter Digest &mdash; {_html.escape(folder)}</h1>
<p class="meta">{date_start} to {date_end} &middot; {len(stories)} stories</p>
{"".join(story_blocks)}
</body>
</html>"""


def _rl_safe(text: str) -> str:
    """Coerce text to Windows-1252 (WinAnsiEncoding) for reportlab standard fonts.

    reportlab's built-in Helvetica/Times/Courier fonts use WinAnsiEncoding.
    Characters outside that range render as replacement boxes.  cp1252 is the
    exact Python codec for WinAnsiEncoding, so encoding + decoding with it
    silently drops anything that can't be represented while keeping all common
    typographic Unicode (curly quotes, dashes, bullets, ellipsis, etc.).
    """
    return text.encode("cp1252", "ignore").decode("cp1252")


def _render_reportlab(data: dict) -> bytes:
    """Render digest to PDF bytes using reportlab platypus for proper layout."""
    from reportlab.lib import colors  # type: ignore[import]
    from reportlab.lib.pagesizes import letter  # type: ignore[import]
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore[import]
    from reportlab.lib.units import inch  # type: ignore[import]
    from reportlab.platypus import (  # type: ignore[import]
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    base = getSampleStyleSheet()
    grey = colors.HexColor("#888888")
    blue = colors.HexColor("#0055aa")
    rule_color = colors.HexColor("#dddddd")

    heading_style = ParagraphStyle(
        "DigestHeading",
        parent=base["Heading1"],
        fontSize=20,
        leading=24,
        spaceAfter=4,
    )
    doc_meta_style = ParagraphStyle(
        "DigestMeta",
        parent=base["Normal"],
        fontSize=10,
        textColor=grey,
        spaceAfter=16,
    )
    story_title_style = ParagraphStyle(
        "StoryTitle",
        parent=base["Normal"],
        fontSize=13,
        leading=17,
        fontName="Helvetica-Bold",
        spaceBefore=0,
        spaceAfter=3,
    )
    meta_style = ParagraphStyle(
        "StoryMeta",
        parent=base["Normal"],
        fontSize=9,
        textColor=grey,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "StoryBody",
        parent=base["Normal"],
        fontSize=11,
        leading=16,
        spaceAfter=2,
    )
    bullet_style = ParagraphStyle(
        "BulletItem",
        parent=body_style,
        leftIndent=18,
        firstLineIndent=-10,
        spaceAfter=2,
    )
    res_label_style = ParagraphStyle(
        "ResourcesLabel",
        parent=base["Normal"],
        fontSize=9,
        textColor=grey,
        spaceBefore=6,
        spaceAfter=2,
    )
    link_style = ParagraphStyle(
        "ResourceLink",
        parent=base["Normal"],
        fontSize=9,
        leftIndent=12,
        spaceAfter=2,
    )

    folder = data.get("folder", "")
    date_start = data.get("date_start", "")
    date_end = data.get("date_end", "")
    stories = data.get("stories", [])

    elements: list = []
    elements.append(Paragraph(
        f"Newsletter Digest \u2014 {_rl_safe(_html.escape(folder))}", heading_style
    ))
    elements.append(Paragraph(
        f"{date_start} to {date_end} \u00b7 {len(stories)} stories",
        doc_meta_style,
    ))

    for story in stories:
        title = story.get("title") or "(untitled)"
        body = story.get("body", "")
        newsletter = story.get("newsletter", "")
        date = story.get("date", "")

        links: list[str] = list(story.get("links") or [])
        single_link = story.get("link")
        if single_link and single_link not in links:
            links.insert(0, single_link)

        elements.append(HRFlowable(
            width="100%",
            thickness=0.5,
            color=rule_color,
            spaceBefore=10,
            spaceAfter=8,
        ))
        elements.append(Paragraph(_rl_safe(_html.escape(title)), story_title_style))
        elements.append(Paragraph(
            f"{_rl_safe(_html.escape(newsletter))} \u00b7 {date}", meta_style
        ))
        # Render body line-by-line so raw \n chars never reach Paragraph (they
        # have no font glyph and render as boxes). Bullet lines get a bullet char
        # and hanging indent; all other lines are plain prose paragraphs.
        for line in body.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.startswith('* ') or line.startswith('- '):
                elements.append(Paragraph(
                    '\u2022\u00a0' + _rl_safe(_html.escape(line[2:])), bullet_style
                ))
            else:
                elements.append(Paragraph(_rl_safe(_html.escape(line)), body_style))

        if links:
            elements.append(Paragraph("Resources:", res_label_style))
            for i, url in enumerate(links[:5], 1):
                url_esc = _html.escape(url)
                elements.append(Paragraph(
                    f'<a href="{url_esc}" color="{blue.hexval()}">Link {i}</a>',
                    link_style,
                ))

        elements.append(Spacer(1, 0.08 * inch))

    doc.build(elements)
    return buf.getvalue()


def _render_pdf(data: dict) -> bytes:
    """Render digest to PDF bytes. Tries weasyprint first, falls back to reportlab."""
    try:
        from weasyprint import HTML  # type: ignore[import]
        return HTML(string=_build_html(data)).write_pdf()
    except Exception as wp_exc:
        logger.warning("weasyprint failed (%s); trying reportlab fallback", wp_exc)
        _wp_exc = wp_exc  # save: Python deletes `as` vars at end of except block

    try:
        return _render_reportlab(data)
    except Exception as rl_exc:
        logger.error("reportlab fallback also failed: %s", rl_exc)
        raise RuntimeError(
            f"Both PDF renderers failed. weasyprint: {_wp_exc}; reportlab: {rl_exc}"
        ) from rl_exc


@router.get("/{digest_id}/pdf")
async def export_digest_pdf(digest_id: str) -> StreamingResponse:
    """Fetch a completed digest by ID and stream it as a PDF attachment."""
    async with async_session() as session:
        result = await session.execute(
            digest_runs.select().where(digest_runs.c.id == digest_id)
        )
        row = result.first()

    if row is None or not row.output_json:
        return JSONResponse(status_code=404, content={"error": "Digest not found"})

    data = json.loads(row.output_json)
    filename = f"digest-{data.get('date_start', digest_id)}.pdf"

    try:
        pdf_bytes = _render_pdf(data)
    except Exception as exc:
        logger.error("PDF rendering failed for digest %s: %s", digest_id, exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
