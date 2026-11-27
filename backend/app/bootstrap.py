"""Application services kept on `app.state` (built at startup, swapped in tests)."""

from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agent_0_resume_parser import ResumeParserAgent
from app.agents.agent_1_profile_inference import ProfileInferenceAgent
from app.connectors.http import HttpFetcher, RetryPolicy
from app.connectors.registry import build_connectors
from app.core.config import Settings
from app.documents.scanner import VirusScanner, build_scanner
from app.llm.cache import LLMCache
from app.llm.client import ClaudeClient
from app.services.discovery_service import DiscoveryService
from app.services.filtering_service import FilteringService
from app.services.pipeline_service import JobPipeline
from app.services.resume_processing import ResumeProcessor
from app.services.scoring_service import ScoringService
from app.storage import StorageBackend, build_storage


def init_services(
    app: FastAPI,
    settings: Settings,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    anthropic_client: Any | None = None,
    storage: StorageBackend | None = None,
    scanner: VirusScanner | None = None,
    http: HttpFetcher | None = None,
) -> None:
    llm = ClaudeClient(
        settings, cache=LLMCache(sessionmaker, settings.llm_cache_ttl_days), client=anthropic_client
    )
    parser = ResumeParserAgent(llm, sessionmaker)
    profiler = ProfileInferenceAgent(llm, sessionmaker)
    storage = storage or build_storage(settings)
    app.state.sessionmaker = sessionmaker
    app.state.llm = llm
    app.state.storage = storage
    app.state.scanner = scanner or build_scanner(settings)
    app.state.parser_agent = parser
    app.state.processor = ResumeProcessor(settings, storage, parser, profiler, sessionmaker)

    # One HTTP pool for all job-board connectors (closed on shutdown).
    http = http or HttpFetcher(
        retry=RetryPolicy(attempts=settings.connector_retry_attempts),
        timeout=settings.connector_timeout_seconds,
    )
    app.state.http = http
    app.state.connectors = build_connectors(http)
    app.state.discovery = DiscoveryService(settings, app.state.connectors, sessionmaker)

    # Phase 6: Discovery -> Deduplication -> Filtering -> Scoring.
    app.state.filtering = FilteringService(sessionmaker)
    app.state.scoring = ScoringService(settings, llm, sessionmaker)
    app.state.pipeline = JobPipeline(
        app.state.discovery, app.state.filtering, app.state.scoring, sessionmaker
    )
    # A new or rebuilt profile changes every score.
    if settings.rescore_on_change:
        app.state.processor.after_profile = app.state.pipeline.rescore
