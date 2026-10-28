"""the security fixtures: the same hermetic app harness as tests/integration."""

from tests.integration._fixtures import alice, bob, qa_app, qa_client, qa_db_template, qa_env, qa_fake

__all__ = ["alice", "bob", "qa_app", "qa_client", "qa_db_template", "qa_env", "qa_fake"]


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    config.addinivalue_line("markers", "live_supabase: opt-in test against a real Supabase project (needs SUPABASE_URL + key)")
