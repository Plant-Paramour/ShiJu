"""Create a consistent local database backup.

SQLite uses its online backup API. PostgreSQL delegates to pg_dump so the
result remains compatible with the normal PostgreSQL restore workflow.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
from pathlib import Path


def backup_sqlite(source: str | Path, destination: str | Path) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.resolve() == source_path.resolve():
        raise ValueError("备份目标不能与源数据库相同")
    with sqlite3.connect(source_path) as source_connection, sqlite3.connect(destination_path) as destination_connection:
        source_connection.backup(destination_connection)
    return destination_path


def backup_postgres(database_url: str, destination: str | Path) -> Path:
    if shutil.which("pg_dump") is None:
        raise RuntimeError("未找到 pg_dump，请安装 PostgreSQL 客户端工具")
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--file", str(destination_path), database_url],
        check=True,
    )
    return destination_path


def main() -> None:
    parser = argparse.ArgumentParser(description="备份诗矩数据库")
    parser.add_argument("--database", required=True, help="SQLite 文件路径或 PostgreSQL URL")
    parser.add_argument("--output", required=True, help="备份文件路径")
    args = parser.parse_args()
    if args.database.startswith(("postgres://", "postgresql://")):
        result = backup_postgres(args.database, args.output)
    else:
        result = backup_sqlite(args.database, args.output)
    print(f"备份完成: {result}")


if __name__ == "__main__":
    main()
