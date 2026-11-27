"""SettingsUpdate must reject everything the settings table's CHECKs reject."""

import pytest
from pydantic import ValidationError

from app.models.setting import Setting
from app.schemas.settings import NOT_NULLABLE, SettingsRead, SettingsUpdate


@pytest.mark.parametrize(
    "body",
    [
        {"remote_preference": "mars"},
        {"application_mode": "YOLO_MODE"},
        {"auto_apply_threshold": 101},
        {"auto_apply_threshold": -1},
        {"daily_application_cap": 201},
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


def test_schema_covers_every_settings_column():
    columns = {c.name for c in Setting.__table__.columns}
    editable = columns - {"id", "created_at", "updated_at"}
    assert set(SettingsUpdate.model_fields) == editable
    assert set(SettingsRead.model_fields) == columns - {"id"}
    not_null = {c.name for c in Setting.__table__.columns if not c.nullable} & editable
    assert NOT_NULLABLE == not_null
