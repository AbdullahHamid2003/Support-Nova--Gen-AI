"""Programmatic Alembic entry points (startup auto-migration and scripts)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from supportnova.core.config import get_settings
from supportnova.core.logging import get_logger

log = get_logger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001_initial"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", (url or get_settings().database_url).replace("%", "%%"))
    return cfg


def upgrade_to_head(url: str | None = None) -> None:
    """Upgrade to the latest revision. A database created before migrations existed (tables but no
    alembic_version) matches the baseline schema: it is stamped at the baseline, then upgraded."""
    import logging

    from supportnova.database.base import get_engine
    logging.getLogger("alembic").setLevel(logging.WARNING)
    engine = get_engine()
    tables = set(inspect(engine).get_table_names())
    cfg = alembic_config(url)
    if "alembic_version" not in tables and "complaints" in tables:
        log.info("existing schema without migration history - stamping the baseline revision")
        command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")
