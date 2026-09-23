from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path) if not str(path).startswith("postgres") else None
        self.url = str(path) if str(path).startswith(("postgres://", "postgresql://")) else os.getenv("DATABASE_URL") if str(path) == "" else None
        self._pool = None
        self._pool_lock = threading.Lock()

    @property
    def is_postgres(self) -> bool:
        return bool(self.url)

    def initialize(self) -> None:
        if self.is_postgres:
            self._initialize_postgres()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            migration_dir = Path(__file__).with_name("migrations")
            for path in sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in applied:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )

    def connect(self):
        if self.is_postgres:
            return self._postgres_connect()
        assert self.path is not None
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def check(self) -> None:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def _postgres_connect(self):
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("生产环境需要安装 psycopg[binary,pool] 才能连接 PostgreSQL") from exc
        with self._pool_lock:
            if self._pool is None:
                self._pool = ConnectionPool(
                    self.url,
                    min_size=1,
                    max_size=int(os.getenv("SHIJU_DATABASE_POOL_MAX", "10")),
                    kwargs={"row_factory": _compat_row_factory},
                    open=True,
                )
                self._pool.wait()
        return _PostgresConnection(self._pool.connection())

    def _initialize_postgres(self) -> None:
        with self._postgres_connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()}
            migration_dir = Path(__file__).with_name("migrations")
            for path in sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in applied:
                    continue
                connection.executescript(_postgresqlize(path.read_text(encoding="utf-8")))
                connection.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))


class _PostgresConnection:
    def __init__(self, connection):
        self._context = connection
        self._connection = None

    def __enter__(self):
        self._connection = self._context.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._context.__exit__(exc_type, exc, tb)

    def execute(self, sql, params=()):
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
        sql = sql.replace("?", "%s")
        return self._connection.execute(sql, params)

    def executescript(self, sql):
        return self._connection.execute(sql)


class _CompatRow(dict):
    """兼容现有 Repository 同时使用 row[0] 和 row['column'] 的访问方式。"""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _compat_row_factory(cursor):
    if cursor.description is None:
        return lambda values: values
    columns = [column.name for column in cursor.description]
    return lambda values: _CompatRow(zip(columns, values))


def _postgresqlize(sql: str) -> str:
    sql = sql.replace("unixepoch()", "EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)")
    sql = sql.replace("COLLATE NOCASE", "")
    sql = sql.replace("instr(messages.content, jobs.id) > 0", "POSITION(jobs.id IN messages.content) > 0")
    sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
    # PostgreSQL expresses INSERT OR IGNORE with an explicit conflict clause.
    sql = re.sub(r"(VALUES\s*\([^;]+?\))\s*;", r"\1 ON CONFLICT DO NOTHING;", sql, flags=re.IGNORECASE | re.DOTALL)
    return sql
