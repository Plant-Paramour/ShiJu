import sqlite3

from tools.backup_database import backup_sqlite
from tools.production_preflight import validate_gateway_config


def test_sqlite_backup_is_readable(tmp_path):
    source = tmp_path / "source.db"
    backup = tmp_path / "backup" / "shiju.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE notes (value TEXT)")
        connection.execute("INSERT INTO notes VALUES ('保留')")
    backup_sqlite(source, backup)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM notes").fetchone()[0] == "保留"


def test_gateway_preflight_does_not_expose_secret(tmp_path, monkeypatch):
    config = tmp_path / "gateway.toml"
    config.write_text(
        "[[endpoints]]\nprovider_id='local'\nbase_url='http://127.0.0.1:9999'\n"
        "model='test'\nsecret_ref='LOCAL_TEST_KEY'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_TEST_KEY", "secret-value")
    assert validate_gateway_config(config, require_secrets=True) == []
