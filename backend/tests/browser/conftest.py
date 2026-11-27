"""Browser tests: real Chromium (Playwright) against the mock ATS pages in
tests/fixtures/ats.py. CI installs Chromium with `playwright install`; locally,
AUTOMATION_BROWSER_PATH may point at another Chromium build."""

import io
import uuid

import pytest
from reportlab.pdfgen import canvas

from app.agents.agent_10_application_agent import ApplicationAgent, ApplyRun
from app.automation.browser_manager import BrowserManager, SessionRegistry
from app.automation.checkpoints import Checkpoint
from app.automation.field_matcher import AnswerFact, ApplicantFacts
from app.automation.form_engine import FilePayload
from app.core.config import Settings
from tests.fixtures.ats import MockATS


def pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


FACTS = ApplicantFacts(
    full_name="Jordan Rivera",
    first_name="Jordan",
    last_name="Rivera",
    email="jordan.rivera@example.com",
    phone="+1 415 555 0100",
    location="San Francisco, CA",
    country="United States",
    linkedin="https://www.linkedin.com/in/jordan-rivera",
    current_company="Acme Payments",
    current_title="Senior Software Engineer",
    years_experience=10,
    answers=(
        AnswerFact("work_authorization", "Are you authorized to work?",
                   "Yes, I am authorized to work in the United States.", True),
        AnswerFact("sponsorship", "Will you require sponsorship?",
                   "No, I do not require visa sponsorship.", True),
        AnswerFact("why_company", "Why do you want to work here?",
                   "Please write this yourself.", False),  # needs review: never typed
    ),
    has_resume_file=True,
    has_cover_letter_file=True,
    cover_letter_text="Dear Acme hiring team, I am applying for the Senior Engineer role.",
)  # fmt: skip
FILES = {
    "resume": FilePayload("Jordan_Rivera_Resume.pdf", "application/pdf", pdf("Resume")),
    "cover_letter": FilePayload(
        "Jordan_Rivera_Cover_Letter.pdf", "application/pdf", pdf("Cover letter")
    ),
}


class Recorder:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str, str, dict]] = []
        self.checkpoints: list[tuple[str, dict]] = []
        self.screenshots: list[tuple[str, str, bytes]] = []
        self.states: list[tuple[str, dict]] = []

    async def log(self, level, step, message, **detail):
        self.logs.append((level, step, message, detail))

    async def checkpoint(self, step, checkpoint):
        self.checkpoints.append((step, checkpoint.as_json()))

    async def screenshot(self, step, label, png):
        assert png.startswith(b"\x89PNG")
        self.screenshots.append((step, label, png))

    async def save_browser_state(self, platform, state):
        self.states.append((platform, state))


@pytest.fixture()
def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql://u:p@127.0.0.1:1/unused",
        automation_submit_timeout_seconds=6,
        automation_action_timeout_ms=4000,
    )


@pytest.fixture()
def mock_ats():
    return MockATS()


@pytest.fixture()
async def browser_manager(settings, mock_ats):
    manager = BrowserManager(settings, context_hook=mock_ats.hook)
    yield manager
    await manager.close()


@pytest.fixture()
async def registry():
    reg = SessionRegistry(max_sessions=2, idle_seconds=600)
    yield reg
    await reg.close_all()


@pytest.fixture()
def agent(settings, browser_manager, registry):
    return ApplicationAgent(settings, browser_manager, registry)


@pytest.fixture()
def make_run():
    def _make(platform: str, url: str, **kw) -> ApplyRun:
        base = {
            "submission_id": uuid.uuid4(), "application_id": uuid.uuid4(),
            "job_id": uuid.uuid4(), "platform": platform, "url": url, "facts": FACTS,
            "files": FILES, "edits": {}, "checkpoint": Checkpoint(),
        }  # fmt: skip
        return ApplyRun(**(base | kw))

    return _make


@pytest.fixture()
def recorder():
    return Recorder()
