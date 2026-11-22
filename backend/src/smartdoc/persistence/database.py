from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


def database_url(path: Path) -> URL:
    return URL.create("sqlite+pysqlite", database=str(path.resolve()))


def create_database_engine(path: Path, *, read_only: bool = False) -> Engine:
    url = database_url(path)
    if read_only:
        url = url.set(database=path.resolve().as_uri(), query={"mode": "ro", "uri": "true"})
    engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": 2})

    @event.listens_for(engine, "connect")
    def configure_connection(connection: SQLiteConnection, _record: object) -> None:
        connection.execute("PRAGMA foreign_keys = ON")

    return engine
