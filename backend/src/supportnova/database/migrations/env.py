"""Alembic environment: the ORM metadata is the single source of the schema."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import supportnova.database.models  # noqa: F401  (register every table)
from supportnova.database.base import Base

config = context.config
if not config.get_main_option("sqlalchemy.url"):  # CLI usage: take DATABASE_URL from the app settings
    from supportnova.core.config import get_settings
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
