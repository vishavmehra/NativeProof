"""Authentication: dev tokens through the API, and Supabase JWT verification with local keys (no network)."""

import time
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from pydantic import SecretStr

from app.core import auth
from app.core.config import Settings
from app.core.errors import Unauthenticated

SUPABASE_URL = "https://project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"


async def test_missing_and_malformed_tokens_are_401(client: httpx.AsyncClient) -> None:
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic dev-alice"}):
        response = await client.get("/api/v1/projects", headers=headers)
        assert response.status_code == 401, headers
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_dev_token_maps_to_stable_uuid5() -> None:
    assert auth.dev_user_id("local") == uuid5(NAMESPACE_URL, "nativeproof-dev:local")


# --- Supabase mode ------------------------------------------------------------------------

EC_KEY = ec.generate_private_key(ec.SECP256R1())
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    ec_jwk = ECAlgorithm.to_jwk(EC_KEY.public_key(), as_dict=True) | {"kid": "ec-1", "alg": "ES256", "use": "sig"}
    rsa_jwk = RSAAlgorithm.to_jwk(RSA_KEY.public_key(), as_dict=True) | {"kid": "rsa-1", "alg": "RS256", "use": "sig"}
    return {"keys": [ec_jwk, rsa_jwk]}


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    return {"sub": str(USER), "aud": "authenticated", "iss": ISSUER, "exp": now + 600, "iat": now, "role": "authenticated"} | overrides


USER = uuid4()


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, auth_mode="supabase", supabase_url=SUPABASE_URL, **overrides)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def fresh_jwks_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "jwks_cache", auth.JwksCache())


@respx.mock
async def test_es256_and_rs256_tokens_verify_against_jwks() -> None:
    route = respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_jwks()))
    es = jwt.encode(_claims(is_anonymous=True), EC_KEY, algorithm="ES256", headers={"kid": "ec-1"})
    rs = jwt.encode(_claims(), RSA_KEY, algorithm="RS256", headers={"kid": "rsa-1"})
    assert await auth.verify_bearer_token(es, _settings()) == (USER, True)
    assert await auth.verify_bearer_token(rs, _settings()) == (USER, False)
    assert route.call_count == 1  # cached


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int(time.time()) - 120},
        {"aud": "anon"},
        {"iss": "https://evil.example/auth/v1"},
        {"sub": "not-a-uuid"},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "bad-sub"],
)
@respx.mock
async def test_invalid_claims_are_rejected(claims: dict[str, Any]) -> None:
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_jwks()))
    token = jwt.encode(_claims(**claims), EC_KEY, algorithm="ES256", headers={"kid": "ec-1"})
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token(token, _settings())


@respx.mock
async def test_missing_exp_unknown_kid_wrong_key_and_tampering_are_rejected() -> None:
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_jwks()))
    claims = _claims()
    del claims["exp"]
    other_key = ec.generate_private_key(ec.SECP256R1())
    good = jwt.encode(_claims(), EC_KEY, algorithm="ES256", headers={"kid": "ec-1"})
    header, payload, signature = good.split(".")
    tampered_payload = jwt.utils.base64url_encode(b'{"sub":"' + str(uuid4()).encode() + b'"}').decode()
    for token in (
        jwt.encode(claims, EC_KEY, algorithm="ES256", headers={"kid": "ec-1"}),
        jwt.encode(_claims(), EC_KEY, algorithm="ES256", headers={"kid": "unknown"}),
        jwt.encode(_claims(), other_key, algorithm="ES256", headers={"kid": "ec-1"}),
        f"{header}.{tampered_payload}.{signature}",
        jwt.encode(_claims(), key="", algorithm="none"),
        "not.a.jwt",
    ):
        with pytest.raises(Unauthenticated):
            await auth.verify_bearer_token(token, _settings())


@respx.mock
async def test_hs256_only_with_configured_secret() -> None:
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=_jwks()))
    token = jwt.encode(_claims(), "legacy-secret-that-is-long-enough-32b", algorithm="HS256")
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token(token, _settings())
    settings = _settings(supabase_jwt_secret=SecretStr("legacy-secret-that-is-long-enough-32b"))
    assert await auth.verify_bearer_token(token, settings) == (USER, False)


@respx.mock
async def test_jwks_outage_rejects_without_crashing() -> None:
    respx.get(JWKS_URL).mock(return_value=httpx.Response(503))
    token = jwt.encode(_claims(), EC_KEY, algorithm="ES256", headers={"kid": "ec-1"})
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token(token, _settings())


async def test_supabase_mode_without_url_rejects() -> None:
    settings = Settings(_env_file=None, auth_mode="supabase")  # type: ignore[call-arg]
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token("x.y.z", settings)
