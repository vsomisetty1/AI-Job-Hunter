"""Career analysis: narrative, trajectory, strengths, gaps, search focus."""

from app.llm.prompts.base import UNTRUSTED_INPUT_NOTICE, PromptTemplate
from app.schemas.candidate_profile import CareerAnalysisOutput

CAREER_ANALYSIS = PromptTemplate(
    name="career_analysis",
    version="1",
    purpose="career_analysis",
    output_model=CareerAnalysisOutput,
    max_tokens=3000,
    system=(
        "You are a career coach reviewing a candidate's history to guide their job search. "
        "From the compact resume JSON, describe the career story in 2-3 sentences, classify "
        "the trajectory, and list strengths, gaps and recommended focus areas. Be specific "
        "and evidence-based: every strength should point to something in the resume, and "
        "gaps should be things a hiring manager would actually notice (for example an "
        "unexplained employment gap, short tenures, or a missing skill common for the "
        "target roles). Be direct and constructive; no generic advice.\n\n" + UNTRUSTED_INPUT_NOTICE
    ),
    user_template="Computed facts: $facts\n\n<resume>\n$resume_json\n</resume>",
)
