"""Entorno de Alembic: usa la misma configuración que la aplicación.

La URL de la base de datos sale de `DATABASE_URL` / `NEXO_DATABASE_URL`, o del
valor por defecto de la app (SQLite en `var/nexo.db`). Nunca hay credenciales
escritas en `alembic.ini`.
"""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registra las tablas en los metadatos)
from app.db import Base, get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_dsn)

# SQLite no crea el directorio de la base de datos por sí mismo.
if settings.database_dsn.startswith("sqlite:///") and not settings.database_dsn.endswith(":memory:"):
    raw = settings.database_dsn.replace("sqlite:///", "", 1)
    Path(raw).parent.mkdir(parents=True, exist_ok=True)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.is_sqlite,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.is_sqlite,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
