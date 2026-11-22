from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from smartdoc.persistence.database import create_database_engine
from smartdoc.persistence.models import Membership, User, Workspace


def test_migration_round_trip_and_no_schema_drift(migration: Config, database: Path):
    command.upgrade(migration, "head")
    command.check(migration)
    engine = create_database_engine(database)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert MigrationContext.configure(connection).get_current_revision()
        assert "workspace_memberships" in inspect(connection).get_table_names()

    command.downgrade(migration, "base")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() is None
        assert "workspaces" not in inspect(connection).get_table_names()

    command.upgrade(migration, "head")
    with engine.connect() as connection:
        assert "workspaces" in inspect(connection).get_table_names()
    engine.dispose()


def test_workspace_membership_constraints(migration: Config, database: Path):
    command.upgrade(migration, "head")
    engine = create_database_engine(database)
    with Session(engine) as session:
        user = User(email="owner@example.test")
        workspace = Workspace(name="Research")
        session.add_all((user, workspace))
        session.flush()
        workspace_id, user_id = workspace.id, user.id
        session.add(Membership(workspace_id=workspace_id, user_id=user_id, role="owner"))
        session.commit()

        session.add(Membership(workspace_id="missing", user_id=user_id, role="viewer"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(Membership(workspace_id=workspace_id, user_id=user_id, role="editor"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        membership = session.scalars(select(Membership)).one()
        membership.role = "invalid"
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.delete(workspace)
        session.commit()
        assert session.scalars(select(Membership)).all() == []
    engine.dispose()
