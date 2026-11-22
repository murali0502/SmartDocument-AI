from pathlib import Path
from typing import Literal

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from smartdoc.persistence.models import Base

DatabaseStatus = Literal["ready", "missing", "migration_required", "unavailable"]


class DatabaseReadiness:
    def __init__(self, path: Path, engine: Engine, migrations_dir: Path) -> None:
        self.path = path
        self.engine = engine
        self.expected_heads = set(ScriptDirectory(str(migrations_dir)).get_heads())

    def check(self) -> DatabaseStatus:
        try:
            if not self.path.is_file():
                return "missing"

            with self.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
                installed_heads = MigrationContext.configure(connection).get_current_heads()
                if set(installed_heads) != self.expected_heads:
                    return "migration_required"
                tables = set(inspect(connection).get_table_names())
                if not set(Base.metadata.tables).issubset(tables):
                    return "migration_required"
        except (OSError, SQLAlchemyError):
            return "unavailable"

        return "ready"
