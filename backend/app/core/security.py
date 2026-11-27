"""Authentication framework (single-user mode).

The app has exactly one user, the owner. Authentication only decides whether
a request may act as that owner:

* AUTH_MODE=none    - every request is the owner. Config refuses this mode
                      unless the server binds to loopback.
* AUTH_MODE=api_key - the request must carry the configured key, either as
                      `X-API-Key: <key>` or `Authorization: Bearer <key>`.

Routes depend on `get_current_user`; a future multi-user mode (e.g. Supabase
Auth JWTs) only has to add another branch here returning a Principal.
"""

import hmac
from dataclasses import dataclass, field

from fastapi import Depends, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError

OWNER_ID = "owner"

# auto_error=False: we raise our own error envelope; these still document the
# schemes in OpenAPI so the docs UI shows an "Authorize" button.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKeyHeader")
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerToken")


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    auth_method: str
    scopes: frozenset[str] = field(default_factory=lambda: frozenset({"owner"}))


def verify_api_key(provided: str | None, expected: str) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    header_key: str | None = Depends(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    if settings.auth_mode == "none":
        principal = Principal(OWNER_ID, settings.owner_name, "none")
    else:
        expected = settings.api_key.get_secret_value() if settings.api_key else ""
        provided = header_key or (bearer.credentials if bearer else None)
        if not expected or not verify_api_key(provided, expected):
            raise AuthenticationError("Missing or invalid API key")
        principal = Principal(OWNER_ID, settings.owner_name, "api_key")
    request.state.principal = principal
    return principal
