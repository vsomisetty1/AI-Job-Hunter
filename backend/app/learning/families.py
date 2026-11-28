"""Job families from job titles (deterministic, explainable).

Used to group applications for analytics ("backend roles got more interviews
than full-stack roles"). The rules only read the title; a title that fits no
rule is "other engineering" or "non-engineering", never guessed further.
"""

import re

FAMILIES: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (key, label, re.compile(pattern, re.IGNORECASE))
    for key, label, pattern in (
        ("management", "Engineering management",
         r"\b(engineering manager|manager,? engineering|director|head of engineering|vp|"
         r"vice president|tech(nical)? lead manager)\b"),
        ("security", "Security", r"\b(security|appsec|infosec|offensive|detection)\b"),
        ("ml_ai", "Machine learning / AI",
         r"\b(machine learning|ml|ai|artificial intelligence|llm|data scientist|research "
         r"(engineer|scientist)|applied scientist|deep learning|nlp|computer vision)\b"),
        ("data", "Data engineering / analytics",
         r"\b(data (engineer|platform|infrastructure|analyst)|analytics engineer|etl|"
         r"business intelligence|bi engineer)\b"),
        ("infrastructure", "Infrastructure / DevOps / SRE",
         r"\b(devops|sre|site reliability|infrastructure|platform engineer|cloud engineer|"
         r"reliability|systems engineer|production engineer|kubernetes)\b"),
        ("mobile", "Mobile", r"\b(ios|android|mobile|react native|flutter)\b"),
        ("frontend", "Frontend", r"\b(front[- ]?end|ui engineer|web engineer|javascript)\b"),
        ("fullstack", "Full stack", r"\b(full[- ]?stack)\b"),
        ("backend", "Backend", r"\b(back[- ]?end|api|server|distributed systems|services)\b"),
        ("qa", "QA / test", r"\b(qa|quality|test|sdet)\b"),
        ("embedded", "Embedded / hardware",
         r"\b(embedded|firmware|hardware|fpga|asic|silicon|electrical)\b"),
        ("engineering", "Software engineering (general)",
         r"\b(software|engineer|developer|programmer|swe)\b"),
    )
)  # fmt: skip
LABELS = {key: label for key, label, _ in FAMILIES} | {"other": "Non-engineering"}


def job_family(title: str) -> str:
    for key, _, pattern in FAMILIES:
        if pattern.search(title):
            return key
    return "other"


def family_label(key: str) -> str:
    return LABELS.get(key, key)
