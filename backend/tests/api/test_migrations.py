"""Alembic: a fresh SQLite database migrates to head, matches the models, and downgrades cleanly."""

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]


def test_upgrade_head_matches_models_and_downgrades(tmp_path: Path) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")
    command.check(config)  # raises when the models and the migrations disagree
    command.downgrade(config, "base")
    command.upgrade(config, "head")
