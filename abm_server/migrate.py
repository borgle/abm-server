"""Run the bundled Alembic migrations.

The migration scripts ship inside the package so hosted deployments can run
``abm-server-migrate`` without a source checkout.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import get_settings


def migration_config() -> Config:
    settings = get_settings()
    root = Path(__file__).resolve().parent / "migrations"
    config = Config()
    config.set_main_option("script_location", str(root))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    config.set_main_option("prepend_sys_path", str(root.parent.parent))
    return config


def main() -> None:
    settings = get_settings()
    settings.ensure_sqlite_directory()
    command.upgrade(migration_config(), "head")


if __name__ == "__main__":
    main()
