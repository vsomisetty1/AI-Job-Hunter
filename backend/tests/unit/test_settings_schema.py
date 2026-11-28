"""SettingsUpdate must reject everything the settings table's CHECKs reject."""

import pytest
from pydantic import ValidationError

from app.models.setting import Setting
from app.schemas.settings import (
    AUTONOMOUS_MODE_DISABLED,
    NOT_NULLABLE,
    RESERVED_FOR_AUTONOMOUS_MODE,
    SettingsRead,
    SettingsUpdate,
)


@pytest.mark.parametrize(
    "body",
    [
        {"remote_preference": "mars"},
        {"application_mode": "YOLO_MODE"},
        {"salary_currency": "dollars"},
        {"salary_min": -5},
        {"salary_min": 200, "salary_target": 100},
        {"unknown_field": 1},
        {"discovery_enabled": None},
        {"extra": None},
    ],
)
def test_invalid_updates_rejected(body):
    with pytest.raises(ValidationError):
        SettingsUpdate.model_validate(body)


def test_partial_update_only_contains_sent_fields():
    patch = SettingsUpdate.model_validate({"salary_min": 100, "work_authorization": None})
    assert patch.changes() == {"salary_min": 100, "work_authorization": None}


def test_lists_are_cleaned_and_currency_uppercased():
    patch = SettingsUpdate.model_validate(
        {"excluded_companies": [" Acme ", "acme", "", "Globex"], "salary_currency": "eur"}
    )
    assert patch.excluded_companies == ["Acme", "Globex"]
    assert patch.salary_currency == "EUR"


@pytest.mark.parametrize(
    "body",
    [
        {"application_mode": "AUTONOMOUS_MODE"},
        {"application_mode": "APPROVAL_MODE"},
        {"auto_apply_threshold": 80},
        {"daily_application_cap": 5},
        {"salary_min": 1, "daily_application_cap": 5},
    ],
)
def test_autonomous_mode_settings_are_not_accepted(body):
    """Disabled until an ADR enables autonomous mode (ADR-016)."""
    with pytest.raises(ValidationError, match="Autonomous mode is not available"):
        SettingsUpdate.model_validate(body)
    assert "confirm" in AUTONOMOUS_MODE_DISABLED


def test_schema_covers_every_settings_column():
    columns = {c.name for c in Setting.__table__.columns}
    editable = columns - {"id", "created_at", "updated_at"} - RESERVED_FOR_AUTONOMOUS_MODE
    assert set(SettingsUpdate.model_fields) == editable
    # application_mode is shown (always APPROVAL_MODE); the reserved numbers are not.
    hidden = {"id", "auto_apply_threshold", "daily_application_cap"}
    assert set(SettingsRead.model_fields) == columns - hidden
    not_null = {c.name for c in Setting.__table__.columns if not c.nullable} & editable
    assert NOT_NULLABLE == not_null
