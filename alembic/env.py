"""Alembic environment configuration for PostgreSQL schema migrations.

This module configures how Alembic interacts with the database for running
schema migrations. It supports both offline (generate SQL) and online
(execute directly) migration modes.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

# this is the Alembic Config object, which provides
# the values of the alembic.ini file, and is passed
# to the run_migrations_online() function.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Read connection string from environment or config
    url = os.getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    )

    # Build the connection string from settings if using PostgreSQL config
    if "://" not in url or url == "driver://user:pass@localhost/dbname":
        from src.core.config import get_settings

        settings = get_settings()
        if settings.postgres_password:
            password = settings.postgres_password.get_secret_value()
        else:
            password = ""
        url = (
            f"postgresql+psycopg://{settings.postgres_user}:{password}@"
            f"{settings.postgres_host}:{settings.postgres_port}/"
            f"{settings.postgres_database}"
        )

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = url

    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
