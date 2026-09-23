from apps.api.database import _PostgresConnection, _postgresqlize


class FakeContext:
    def __init__(self):
        self.entered = False
        self.executed = []

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.entered = False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return self


def test_postgres_connection_context_and_placeholders():
    fake = FakeContext()
    with _PostgresConnection(fake) as connection:
        connection.execute("BEGIN IMMEDIATE; SELECT ?", (1,))
    assert fake.entered is False
    assert fake.executed[0] == ("BEGIN; SELECT %s", (1,))


def test_postgresqlize_sqlite_specific_syntax():
    sql = _postgresqlize("INSERT OR IGNORE INTO t VALUES (1, unixepoch());")
    assert "INSERT OR IGNORE" not in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "unixepoch" not in sql
