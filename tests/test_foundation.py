"""
Milestone 0 tests: prove the project is wired together correctly.

Does NOT test application schema — there isn't one yet. See
docs/ROADMAP.md — Milestone 1 adds the first real schema tests.
"""

import sqlite3
from pathlib import Path

import database


def test_get_connection_returns_sqlite_connection():
    conn = database.get_connection()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_get_connection_creates_data_directory():
    database.get_connection()
    assert database.DATA_DIR.exists()


def test_database_is_reachable():
    conn = database.get_connection()
    result = conn.execute("SELECT 1").fetchone()
    assert result == (1,)
    conn.close()


def test_db_file_created_under_data_dir():
    database.get_connection()
    assert database.DB_PATH.parent == database.DATA_DIR
    assert database.DB_PATH.exists()


def test_export_database_bytes_returns_valid_sqlite_file():
    database.get_connection()  # ensure the schema exists
    exported = database.export_database_bytes()
    assert exported[:16] == b"SQLite format 3\x00"


def test_export_database_bytes_reflects_current_data(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")

    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO recipes (name, cook_time_minutes, family_enjoyment, seasonality, servings)
        VALUES ('Export Test Recipe', 10, 3, 'all-season', 2)
        """
    )
    conn.commit()
    conn.close()

    exported = database.export_database_bytes()
    backup_path = tmp_path / "exported.db"
    backup_path.write_bytes(exported)

    backup_conn = sqlite3.connect(backup_path)
    names = [
        row[0]
        for row in backup_conn.execute("SELECT name FROM recipes WHERE name = 'Export Test Recipe'")
    ]
    backup_conn.close()
    assert names == ["Export Test Recipe"]


def test_export_database_bytes_does_not_modify_original():
    conn = database.get_connection()
    before = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    conn.close()

    database.export_database_bytes()

    conn = database.get_connection()
    after = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    conn.close()
    assert before == after
