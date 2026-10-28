"""the integration fixtures (definitions live in _fixtures.py so tests/security can share them)."""

from tests.integration._fixtures import alice, bob, qa_app, qa_client, qa_db_template, qa_env, qa_fake

__all__ = ["alice", "bob", "qa_app", "qa_client", "qa_db_template", "qa_env", "qa_fake"]
