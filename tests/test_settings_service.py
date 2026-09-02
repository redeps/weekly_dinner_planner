"""
Milestone 14 tests: app-wide settings (services/settings.py) — the
single-row `app_settings` table holding the global default household size.
"""

import pytest

import database
from services import settings as settings_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def test_get_default_household_size_seeds_default_on_first_read(conn):
    assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 0
    size = settings_service.get_default_household_size(conn)
    assert size == settings_service.DEFAULT_HOUSEHOLD_SIZE
    assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 1


def test_get_default_household_size_does_not_reseed_on_second_read(conn):
    settings_service.set_default_household_size(conn, 6)
    assert settings_service.get_default_household_size(conn) == 6
    assert settings_service.get_default_household_size(conn) == 6
    assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 1


def test_set_default_household_size_updates_existing_row(conn):
    settings_service.get_default_household_size(conn)  # seeds the row
    settings_service.set_default_household_size(conn, 5)
    assert settings_service.get_default_household_size(conn) == 5
    assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 1


def test_set_default_household_size_rejects_less_than_one(conn):
    with pytest.raises(ValueError):
        settings_service.set_default_household_size(conn, 0)


def test_effective_household_size_uses_override_when_set():
    assert settings_service.effective_household_size(6, 4) == 6


def test_effective_household_size_falls_back_to_default_when_none():
    assert settings_service.effective_household_size(None, 4) == 4
