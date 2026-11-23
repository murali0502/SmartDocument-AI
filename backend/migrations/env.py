from alembic import context

from smartdoc.config import Settings
from smartdoc.persistence import ingestion_models, ncm_models, nlp_models, structure_models  # noqa: F401
from smartdoc.persistence.database import create_database_engine, database_url
from smartdoc.persistence.models import Base


def run_migrations() -> None:
    path = Settings().database_path
    if context.is_offline_mode():
        context.configure(url=database_url(path), target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(path)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode = WAL")
            connection.commit()
            with connection.begin():
                # The sqlite3 driver's legacy mode does not start a transaction for DDL.
                connection.exec_driver_sql("BEGIN")
                context.configure(connection=connection, target_metadata=Base.metadata)
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
