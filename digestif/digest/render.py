"""Digest rendering engine using Jinja2, markdown-it-py, and premailer."""

from pathlib import Path
from typing import Any

import jinja2
import markdown_it
import premailer

from digestif.llm.schemas import EditorPassResult
from digestif.observability import logger
from digestif.settings import settings


class DigestRenderer:
    def __init__(self) -> None:
        templates_dir = Path(__file__).parent / "templates"
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates_dir)),
            autoescape=False,
        )
        self.md = markdown_it.MarkdownIt()

    def render_digest(
        self,
        digest_date: str,
        editor_result: EditorPassResult,
        full_sections_md: list[str],
        quick_hits_md: list[str],
        section_titles: list[dict[str, Any]],
        saved_count: int,
        total_original_minutes: float,
        letting_go: list[dict[str, Any]] | None = None,
        wpm: int = 230,
    ) -> dict[str, Any]:
        """Renders standalone HTML, inlined email HTML, and Telegram teaser text."""
        # Convert markdown sections to HTML
        sections_html = [self.md.render(sec) for sec in full_sections_md]
        quick_hits_html = [self.md.render(hit) for hit in quick_hits_md]

        # Calculate word count
        all_text = " ".join(full_sections_md) + " " + " ".join(quick_hits_md)
        word_count = len(all_text.split())
        est_minutes = max(1.0, round(word_count / float(wpm), 1))

        template_ctx = {
            "digest_date": digest_date,
            "editor": editor_result,
            "full_sections": sections_html,
            "quick_hits": quick_hits_html,
            "section_titles": section_titles,
            "quick_hits_count": len(quick_hits_md),
            "saved_count": saved_count,
            "total_original_minutes": round(total_original_minutes, 1),
            "est_minutes": est_minutes,
            "letting_go": letting_go or [],
        }

        # 1. Render Standalone HTML
        digest_tpl = self.jinja_env.get_template("digest.html")
        html_out = digest_tpl.render(**template_ctx)

        # Save HTML file to DATA_DIR/digests/
        digests_dir = settings.digests_dir
        html_file = digests_dir / f"digest-{digest_date}.html"
        html_file.write_text(html_out, encoding="utf-8")

        # 2. Render Inlined Email HTML
        email_tpl = self.jinja_env.get_template("email.html")
        raw_email_html = email_tpl.render(**template_ctx)
        try:
            inlined_email_html = premailer.transform(raw_email_html)
        except Exception as e:
            logger.warning(
                "Premailer transformation failed, falling back to raw email HTML", error=str(e)
            )
            inlined_email_html = raw_email_html

        email_file = digests_dir / f"digest-{digest_date}-email.html"
        email_file.write_text(inlined_email_html, encoding="utf-8")

        # 3. Render Telegram Teaser
        teaser_tpl = self.jinja_env.get_template("telegram_teaser.html")
        teaser_text = teaser_tpl.render(**template_ctx).strip()

        logger.info(
            "Rendered digest successfully",
            date=digest_date,
            word_count=word_count,
            est_minutes=est_minutes,
            html_file=str(html_file),
        )

        return {
            "html_path": str(html_file),
            "email_html_path": str(email_file),
            "html_content": html_out,
            "email_html_content": inlined_email_html,
            "telegram_teaser": teaser_text,
            "word_count": word_count,
            "est_minutes": est_minutes,
        }


renderer = DigestRenderer()
