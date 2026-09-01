"""
Milestone 0 tests, updated for Milestone 13 Phase 1: prove the Postgres
connection layer — schema migrations and per-test schema isolation — is
wired together correctly. See docs/DECISIONS.md — Milestone 13 hosting
architecture.
"""

import io
import zipfile

import psycopg

import database


def test_get_connection_returns_postgres_connection():
    conn = database.get_connection()
    assert isinstance(conn, psycopg.Connection)
    conn.close()


def test_get_connection_defaults_to_public_schema():
    conn = database.get_connection()
    schema = conn.execute("SELECT current_schema()").fetchone()[0]
    conn.close()
    assert schema == "public"


def test_database_is_reachable():
    conn = database.get_connection()
    result = conn.execute("SELECT 1").fetchone()
    assert result == (1,)
    conn.close()


def test_get_connection_with_identity_uses_isolated_schema(tmp_path):
    conn = database.get_connection(identity=tmp_path)
    schema = conn.execute("SELECT current_schema()").fetchone()[0]
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.close()
    assert schema == database.schema_name_for(tmp_path)


def test_get_connection_applies_schema_migrations(tmp_path):
    conn = database.get_connection(identity=tmp_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        ).fetchall()
    }
    schema = database.schema_name_for(tmp_path)
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.close()
    assert {
        "recipes",
        "recipe_ingredients",
        "week_plans",
        "plan_days",
        "cook_history",
        "schema_version",
    } <= tables


def test_export_database_bytes_returns_valid_zip_file():
    database.get_connection()  # ensure the schema exists
    exported = database.export_database_bytes()
    assert exported[:4] == b"PK\x03\x04"


def test_export_database_bytes_reflects_current_data(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)

    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO recipes (name, cook_time_minutes, family_enjoyment, seasonality, servings)
        VALUES ('Export Test Recipe', 10, 3, 'all-season', 2)
        """
    )

    exported = database.export_database_bytes()

    with zipfile.ZipFile(io.BytesIO(exported)) as zf:
        recipes_csv = zf.read("recipes.csv").decode()

    schema = database.schema_name_for(tmp_path)
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.close()

    assert "Export Test Recipe" in recipes_csv


def test_export_database_bytes_does_not_modify_original():
    conn = database.get_connection()
    before = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    conn.close()

    database.export_database_bytes()

    conn = database.get_connection()
    after = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    conn.close()
    assert before == after
