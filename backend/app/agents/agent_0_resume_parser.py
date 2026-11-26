"""Agent 0: resume parser.

Deterministic parsing always runs first. Claude is called only when it is
configured, allowed, and the parser reports weak sections; it then receives
only the text of those sections (or the whole document when the layout was
not recognised at all). One call at most per parse.
"""

import logging
import uuid

from app.agents.base import Agent
from app.documents.sandbox import ExtractedDocument
from app.llm.client import LLMError
from app.llm.prompts import RESUME_PARSE, ResumeExtractionOutput
from app.parsing.parser import ParseResult, parse_document, weak_sections
from app.parsing.skills import dedupe_skills
from app.schemas.parsed_resume import ParsedResume

logger = logging.getLogger(__name__)

# Above this size the resume is not sent to Claude (and the user is told why).
MAX_LLM_INPUT_CHARS = 60_000


def _section_text(result: ParseResult, doc: ExtractedDocument, names: list[str]) -> str:
    parts = []
    for name in names:
        lines = result.sections.get("header" if name == "contact" else name, [])
        if name == "contact" and not lines:
            lines = [ln.text for ln in doc.lines[:10]]
        if lines:
            parts.append(f"## {name.upper()}\n" + "\n".join(lines))
    return "\n\n".join(parts)


def merge_extraction(
    resume: ParsedResume, llm: ResumeExtractionOutput, sections: list[str] | None
) -> ParsedResume:
    """Overlay Claude's sections onto the deterministic result."""
    merged = resume.model_copy(deep=True)
    wanted = set(sections) if sections is not None else None

    def take(name: str) -> bool:
        return (wanted is None or name in wanted) and getattr(llm, name) not in (None, [])

    if take("contact") and llm.contact:
        # Regex-found email/phone are exact; Claude fills what is missing.
        for field, value in llm.contact.model_dump().items():
            if value and not getattr(merged.contact, field):
                setattr(merged.contact, field, value)
    for name in ("experience", "education", "certifications", "projects", "publications",
                 "awards", "summary"):  # fmt: skip
        if take(name):
            setattr(merged, name, getattr(llm, name))
    if wanted is None and llm.skills:
        merged.skills = dedupe_skills([*merged.skills, *llm.skills])
    mined = [s for e in merged.experience for s in e.skills]
    merged.skills = dedupe_skills([*merged.skills, *mined])
    return merged


class ResumeParserAgent(Agent):
    name = "agent_0_resume_parser"

    async def run(
        self, doc: ExtractedDocument, *, use_llm: bool, resume_id: uuid.UUID | None = None
    ) -> ParsedResume:
        async with self.track(
            input_summary={
                "resume_id": str(resume_id) if resume_id else None,
                "lines": len(doc.lines),
                "use_llm": use_llm,
            }  # fmt: skip
        ) as run:
            result = parse_document(doc)
            resume = result.resume
            weak = weak_sections(result)
            needs_llm = weak is None or bool(weak)
            run.output_summary.update(
                {"confidence": resume.meta.confidence, "weak_sections": weak if weak else []}
            )
            if not (use_llm and needs_llm and self.llm.enabled):
                if needs_llm and use_llm and not self.llm.enabled:
                    resume.meta.warnings.append(
                        "Some sections were hard to read; configure Claude for better results."
                    )
                return resume

            text = doc.text if weak is None else _section_text(result, doc, list(weak))
            if len(text) > MAX_LLM_INPUT_CHARS:
                resume.meta.warnings.append("Resume too long for AI-assisted parsing.")
                return resume
            try:
                llm_result = await self.llm.structured(
                    RESUME_PARSE,
                    sections="all sections" if weak is None else ", ".join(weak),
                    text=text,
                )
            except LLMError as exc:
                logger.warning("AI-assisted parsing failed: %s", exc.message)
                resume.meta.warnings.append(f"AI-assisted parsing unavailable: {exc.message}")
                run.output_summary["llm_error"] = exc.code
                return resume

            self.record(run, RESUME_PARSE.name, llm_result)
            merged = merge_extraction(
                resume, llm_result.output, None if weak is None else list(weak)
            )
            merged.meta.method = "llm_assisted"
            merged.meta.llm_sections = ["all"] if weak is None else list(weak)
            return merged
