"""Import every model so Base.metadata is complete (Alembic, tests)."""

from app.models.agent_run import AgentRun
from app.models.application import Application
from app.models.application_answer import ApplicationAnswer
from app.models.application_event import ApplicationEvent
from app.models.base import Base
from app.models.browser_session import BrowserSession
from app.models.candidate_profile import CandidateProfile
from app.models.company import Company
from app.models.cover_letter import CoverLetter
from app.models.job import Job
from app.models.job_score import JobScore
from app.models.llm_cache_entry import LLMCacheEntry
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.models.setting import Setting

__all__ = [
    "AgentRun",
    "Application",
    "ApplicationAnswer",
    "ApplicationEvent",
    "Base",
    "BrowserSession",
    "CandidateProfile",
    "Company",
    "CoverLetter",
    "Job",
    "JobScore",
    "LLMCacheEntry",
    "Resume",
    "ResumeVersion",
    "Setting",
]
