"""Skill extraction from experience and project descriptions.

Only used when the deterministic extractor finds few skills, e.g. for
non-software careers whose skills the built-in taxonomy does not know.
"""

from app.llm.prompts.base import UNTRUSTED_INPUT_NOTICE, PromptTemplate
from app.schemas.candidate_profile import SkillExtractionOutput

SKILL_EXTRACTION = PromptTemplate(
    name="skill_extraction",
    version="1",
    purpose="skill_extraction",
    output_model=SkillExtractionOutput,
    max_tokens=2000,
    system=(
        "You extract skills from resume text for job matching. Return skills as short, "
        "conventional names a job posting would use (e.g. 'PostgreSQL', 'Financial Modeling', "
        "'Inventory Management'). Include a skill only if the text shows it was used; do not "
        "infer skills from job titles alone. No duplicates across categories.\n\n"
        + UNTRUSTED_INPUT_NOTICE
    ),
    user_template="Skills already found (do not repeat): $known\n\n<resume>\n$text\n</resume>",
)
