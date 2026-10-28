"""AUTH_MODE=dev is refused in production (contracts/README.md §4, D-020) without leaking secrets."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.integration._support import running_app

DUMMY = "sk-qa-DUMMY-guard-0a2c4e6f8b"


def test_production_refuses_dev_auth() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=dev is refused"):
        Settings(_env_file=None, app_env="production", auth_mode="dev")


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_dev_auth_is_allowed_outside_production(app_env: str) -> None:
    assert Settings(_env_file=None, app_env=app_env, auth_mode="dev").auth_mode == "dev"


def test_production_accepts_supabase_auth() -> None:
    settings = Settings(_env_file=None, app_env="production", auth_mode="supabase", supabase_url="https://x.supabase.co")
    assert settings.auth_mode == "supabase"


def test_secrets_are_masked_in_settings_repr() -> None:
    settings = Settings(_env_file=None, nebius_api_key=DUMMY, qloo_api_key=DUMMY, openrouter_api_key=DUMMY)
    if DUMMY in repr(settings) or DUMMY in str(settings.model_dump()):
        pytest.fail("a secret is visible in Settings repr/model_dump", pytrace=False)


def test_settings_error_does_not_echo_secrets() -> None:
    """A misconfigured production deploy logs this error at startup; it must not contain provider keys."""
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="dev",
            nebius_api_key=DUMMY,
            openrouter_api_key=DUMMY,
            qloo_api_key=DUMMY,
            supabase_jwt_secret=DUMMY,
        )
    if DUMMY in str(caught.value) or DUMMY in repr(caught.value.errors()):
        pytest.fail("the settings ValidationError echoes a configured secret", pytrace=False)


async def test_app_refuses_to_start_in_production_with_dev_auth(
    qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev")
    with pytest.raises((ValidationError, RuntimeError)):
        async with running_app():
            pass
