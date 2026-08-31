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
