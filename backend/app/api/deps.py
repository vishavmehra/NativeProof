"""Request dependencies shared by every route.

`get_current_user` verifies the bearer token (Supabase JWT, or the development-only
dev token) without changing its signature. See contracts/README.md, "Authentication".
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import INVALID_TOKEN, verify_bearer_token
from app.core.config import get_settings
from app.core.errors import Unauthenticated

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    """The authenticated caller. `id` is the Supabase user id (JWT `sub`)."""

    id: UUID
    is_anonymous: bool = False


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthUser:
    if credentials is None or not credentials.credentials:
        raise Unauthenticated(INVALID_TOKEN)
    user_id, is_anonymous = await verify_bearer_token(credentials.credentials, get_settings())
    return AuthUser(id=user_id, is_anonymous=is_anonymous)


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
Limit = Annotated[int, Query(ge=1, le=100, description="Maximum records returned.")]
Offset = Annotated[int, Query(ge=0, description="Number of records skipped.")]
