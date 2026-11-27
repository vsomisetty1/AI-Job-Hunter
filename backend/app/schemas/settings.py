"""Settings schemas.

Every CHECK constraint on the `settings` table is mirrored here so invalid
input is a 422 from validation instead of a database error.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import APIModel, ORMModel

RemotePreference = Literal["remote_only", "hybrid", "onsite", "any"]
ApplicationMode = Literal["APPROVAL_MODE", "AUTONOMOUS_MODE"]

# Columns that are NOT NULL in the database: an explicit null is rejected.
NOT_NULLABLE = frozenset(
    {
        "preferred_locations",
        "remote_preference",
        "job_types",
        "salary_currency",
        "requires_sponsorship",
        "excluded_companies",
        "excluded_keywords",
        "application_mode",
        "auto_apply_threshold",
        "daily_application_cap",
        "discovery_enabled",
        "extra",
    }
)


def _clean_list(values: list[str]) -> list[str]:
    """Trim, drop blanks, de-duplicate case-insensitively, keep first spelling and order."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = v.strip()
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


class SettingsRead(ORMModel):
    preferred_locations: list[str]
    remote_preference: RemotePreference
    job_types: list[str]
    salary_min: int | None
    salary_target: int | None
    salary_currency: str
    work_authorization: str | None
    visa_status: str | None
    requires_sponsorship: bool
    excluded_companies: list[str]
    excluded_keywords: list[str]
    application_mode: ApplicationMode
    auto_apply_threshold: int
    daily_application_cap: int
    discovery_enabled: bool
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SettingsUpdate(APIModel):
    """PATCH body: only fields that are sent are changed; send null to clear nullable ones."""

    preferred_locations: list[str] | None = None
    remote_preference: RemotePreference | None = None
    job_types: list[str] | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_target: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    work_authorization: str | None = Field(default=None, max_length=200)
    visa_status: str | None = Field(default=None, max_length=200)
    requires_sponsorship: bool | None = None
    excluded_companies: list[str] | None = None
    excluded_keywords: list[str] | None = None
    application_mode: ApplicationMode | None = None
    auto_apply_threshold: int | None = Field(default=None, ge=0, le=100)
    daily_application_cap: int | None = Field(default=None, ge=0, le=200)
    discovery_enabled: bool | None = None
    extra: dict[str, Any] | None = None

    @field_validator("preferred_locations", "job_types", "excluded_companies", "excluded_keywords")
    @classmethod
    def _clean(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _clean_list(v)

    @field_validator("salary_currency", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check(self) -> SettingsUpdate:
        nulls = sorted(f for f in self.model_fields_set & NOT_NULLABLE if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"fields cannot be null: {', '.join(nulls)}")
        if (
            self.salary_min is not None
            and self.salary_target is not None
            and self.salary_min > self.salary_target
        ):
            raise ValueError("salary_min must be <= salary_target")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
