"""Prompt registry. Every template the app sends to Claude is listed here."""

from app.llm.prompts.base import PromptTemplate
from app.llm.prompts.career_analysis import CAREER_ANALYSIS
from app.llm.prompts.profile_inference import PROFILE_INFERENCE
from app.llm.prompts.resume_parse import RESUME_PARSE, ResumeExtractionOutput
from app.llm.prompts.skill_extraction import SKILL_EXTRACTION

PROMPTS: dict[str, PromptTemplate] = {
    p.name: p for p in (RESUME_PARSE, PROFILE_INFERENCE, CAREER_ANALYSIS, SKILL_EXTRACTION)
}

__all__ = [
    "CAREER_ANALYSIS",
    "PROFILE_INFERENCE",
    "PROMPTS",
    "RESUME_PARSE",
    "SKILL_EXTRACTION",
    "PromptTemplate",
    "ResumeExtractionOutput",
]
