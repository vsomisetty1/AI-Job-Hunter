import json
import logging

import pytest

from app.core.logging import configure_logging, request_id_var


@pytest.fixture()
def restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_json_logs_are_one_object_per_line(capsys, restore_logging):
    configure_logging("INFO", json_logs=True)
    log = logging.getLogger("app.test")
    token = request_id_var.set("req-123")
    try:
        log.info("hello %s", "world", extra={"job_id": "j1", "count": 3})
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("failed")
    finally:
        request_id_var.reset(token)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    first, second = lines
    assert first["msg"] == "hello world"
    assert first["level"] == "INFO" and first["logger"] == "app.test"
    assert first["request_id"] == "req-123"
    assert first["job_id"] == "j1" and first["count"] == 3
    assert first["ts"].endswith("+00:00")
    assert second["level"] == "ERROR" and "ValueError: boom" in second["exc"]


def test_text_logs_include_request_id(capsys, restore_logging):
    configure_logging("DEBUG", json_logs=False)
    token = request_id_var.set("abc")
    try:
        logging.getLogger("app.test").debug("plain")
    finally:
        request_id_var.reset(token)
    out = capsys.readouterr().out
    assert "[abc] app.test: plain" in out


def test_uvicorn_access_log_suppressed(restore_logging):
    configure_logging("INFO")
    # Our middleware writes the access log; uvicorn's would duplicate it.
    assert not logging.getLogger("uvicorn.access").isEnabledFor(logging.INFO)
