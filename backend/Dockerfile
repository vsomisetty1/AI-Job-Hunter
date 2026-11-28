# syntax=docker/dockerfile:1
# Backend image: FastAPI app, migrations, and Chromium for application automation.
#
#   docker compose build backend          (see DEPLOYMENT.md)
#   --build-arg INSTALL_BROWSER=false     smaller image without Chromium; automation
#                                         runs then cannot start a browser
#
# Runs as an unprivileged user; data lives in the /data volume (stored files).
# Migrations run on start (MIGRATE_ON_START=true). One worker only (ADR-005).

ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------- dependencies
FROM base AS deps
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --requirement /tmp/requirements.txt

# --------------------------------------------------------------------- runtime
FROM base AS runtime
ARG INSTALL_BROWSER=true
ENV PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
COPY --from=deps /opt/venv /opt/venv
# Playwright's bundled Node driver needs libatomic (absent from the slim image).
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Headless Chromium and its system libraries (Playwright's own build, matching the
# pinned playwright package). Headed mode needs a display: run the backend natively
# to watch a run or solve a CAPTCHA (DEPLOYMENT.md).
RUN if [ "$INSTALL_BROWSER" = "true" ]; then \
      playwright install --with-deps --only-shell chromium \
      && rm -rf /var/lib/apt/lists/* /root/.cache; \
    fi

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /data/storage \
    && chown -R app:app /data

WORKDIR /app
COPY --chown=app:app alembic.ini pyproject.toml ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app app ./app
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER app
# Inside the container the server listens on all interfaces; Compose publishes the
# port on the host's 127.0.0.1 only (CONTAINER_LOOPBACK_ONLY, ADR-016).
ENV APP_ENV=production \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    CONTAINER_LOOPBACK_ONLY=true \
    LOCAL_STORAGE_DIR=/data/storage \
    MIGRATE_ON_START=true
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=4)"]
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "app"]
