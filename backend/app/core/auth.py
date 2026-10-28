"""Bearer-token verification (contracts/README.md section 4).

AUTH_MODE=dev:      `dev-<label>` maps to uuid5(NAMESPACE_URL, "nativeproof-dev:<label>").
AUTH_MODE=supabase: ES256/RS256 against the project's JWKS (cached), HS256 only when
                    SUPABASE_JWT_SECRET is set. exp, aud=authenticated, and iss are required.
"""

import logging
import re
import time
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import jwt

from app.core.config import Settings
from app.core.errors import Unauthenticated

logger = logging.getLogger("nativeproof.auth")

DEV_TOKEN = re.compile(r"^dev-([A-Za-z0-9_.-]{1,64})$")
ASYMMETRIC_ALGORITHMS = {"ES256", "RS256"}
AUDIENCE = "authenticated"
JWKS_TTL_SECONDS = 600
JWKS_MIN_REFRESH_SECONDS = 30
JWKS_TIMEOUT_SECONDS = 5
CLOCK_SKEW_SECONDS = 30
INVALID_TOKEN = "The access token is missing, invalid, or expired. Sign in again."


def dev_user_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nativeproof-dev:{label}")


class JwksCache:
    """Signing keys by kid. Refreshes after the TTL, or early (rate-limited) for an unknown kid."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.keys: dict[str, jwt.PyJWK] = {}
        self.fetched_at = float("-inf")

    async def get(self, url: str, kid: str) -> jwt.PyJWK | None:
        age = time.monotonic() - self.fetched_at
        if url != self.url or age > JWKS_TTL_SECONDS or (kid not in self.keys and age > JWKS_MIN_REFRESH_SECONDS):
            await self._refresh(url)
        return self.keys.get(kid)

    async def _refresh(self, url: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
                response.raise_for_status()
                entries = response.json().get("keys", [])
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            logger.warning("JWKS fetch failed; keeping cached keys", extra={"error": type(exc).__name__})
            return
        keys: dict[str, jwt.PyJWK] = {}
        for entry in entries:
            try:
                key = jwt.PyJWK(entry)
            except jwt.PyJWTError:
                continue  # unsupported or symmetric entries are skipped
            if entry.get("kid"):
                keys[entry["kid"]] = key
        self.url, self.keys, self.fetched_at = url, keys, time.monotonic()


jwks_cache = JwksCache()


async def verify_bearer_token(token: str, settings: Settings) -> tuple[UUID, bool]:
    """Return (user_id, is_anonymous) or raise Unauthenticated."""
    if settings.auth_mode == "dev":
        match = DEV_TOKEN.match(token)
        if not match:
            raise Unauthenticated(INVALID_TOKEN)
        return dev_user_id(match.group(1)), False
    return await _verify_supabase(token, settings)


async def _verify_supabase(token: str, settings: Settings) -> tuple[UUID, bool]:
    if not settings.supabase_url:
        logger.error("AUTH_MODE=supabase but SUPABASE_URL is not set; rejecting every token")
        raise Unauthenticated(INVALID_TOKEN)
    issuer = settings.supabase_url.rstrip("/") + "/auth/v1"
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise Unauthenticated(INVALID_TOKEN) from None
    algorithm = header.get("alg")
    key: object
    if algorithm in ASYMMETRIC_ALGORITHMS and isinstance(header.get("kid"), str):
        jwk = await jwks_cache.get(f"{issuer}/.well-known/jwks.json", header["kid"])
        if jwk is None:
            raise Unauthenticated(INVALID_TOKEN)
        key = jwk.key
    elif algorithm == "HS256" and settings.supabase_jwt_secret is not None:
        key = settings.supabase_jwt_secret.get_secret_value()
    else:
        raise Unauthenticated(INVALID_TOKEN)
    try:
        claims = jwt.decode(
            token,
            key,  # type: ignore[arg-type]
            algorithms=[algorithm],
            audience=AUDIENCE,
            issuer=issuer,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        return UUID(str(claims["sub"])), claims.get("is_anonymous") is True
    except (jwt.PyJWTError, ValueError):
        raise Unauthenticated(INVALID_TOKEN) from None
