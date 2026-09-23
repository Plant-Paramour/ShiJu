from __future__ import annotations

import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql


SQLITE_PATH = Path("var/shiju.db")
POSTGRES_URL = "postgresql://postgres:159487@127.0.0.1:5432/shiju"


def main() -> None:
    source = sqlite3.connect(SQLITE_PATH)
    source.row_factory = sqlite3.Row
    tables = [
        row[0]
        for row in source.execute(
            "select name from sqlite_master where type='table' "
            "and name not like 'sqlite_%' and name <> 'schema_migrations' "
            "order by name"
        )
    ]
    with psycopg.connect(POSTGRES_URL) as target:
        with target.cursor() as cursor:
            cursor.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(name) for name in tables)
                )
            )
            for table in tables:
                cursor.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER ALL").format(sql.Identifier(table)))
            for table in tables:
                columns = [row[1] for row in source.execute(f'pragma table_info("{table}")')]
                rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
                if not rows:
                    continue
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                cursor.executemany(statement, [tuple(row) for row in rows])
                print(f"{table}: {len(rows)}")
            for table in tables:
                cursor.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER ALL").format(sql.Identifier(table)))
            for table in tables:
                cursor.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                    "AND table_name=%s AND column_name='id'",
                    (table,),
                )
                if cursor.fetchone() is None:
                    continue
                cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                sequence = cursor.fetchone()[0]
                if sequence:
                    cursor.execute(
                        sql.SQL("SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {}), 1), true)").format(
                            sql.Identifier(table)
                        ),
                        (sequence,),
                    )
    source.close()
    print("迁移完成")


if __name__ == "__main__":
    main()
