"""Run the API: `python -m app`.

Preferred over calling uvicorn directly: host and port come from config,
which refuses a non-loopback host unless AUTH_MODE=api_key, and it always
runs a single worker (the scheduler and background tasks are in-process).
"""

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        workers=1,
        reload=settings.app_env == "development",
        log_config=None,  # app.core.logging configures logging
    )


if __name__ == "__main__":
    main()
