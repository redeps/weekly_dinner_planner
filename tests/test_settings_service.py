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


# --- scale_ingredient_quantity ---


def test_scale_ingredient_quantity_none_passes_through():
    assert settings_service.scale_ingredient_quantity(None, recipe_servings=4, household_size=8) is None


def test_scale_ingredient_quantity_scales_proportionally():
    assert settings_service.scale_ingredient_quantity(2.0, recipe_servings=4, household_size=8) == 4.0


def test_scale_ingredient_quantity_unchanged_when_sizes_equal():
    assert settings_service.scale_ingredient_quantity(3.0, recipe_servings=4, household_size=4) == 3.0


def test_scale_ingredient_quantity_rounds_to_two_decimals():
    assert settings_service.scale_ingredient_quantity(1.0, recipe_servings=3, household_size=1) == 0.33


# --- effective_ingredient_quantity ---


def test_effective_ingredient_quantity_scales_normal_recipe():
    result = settings_service.effective_ingredient_quantity(
        2.0,
        recipe_servings=4,
        is_special_occasion=False,
        household_size_override=None,
        default_household_size=8,
    )
    assert result == 4.0


def test_effective_ingredient_quantity_special_occasion_unscaled_with_no_override():
    result = settings_service.effective_ingredient_quantity(
        2.0,
        recipe_servings=4,
        is_special_occasion=True,
        household_size_override=None,
        default_household_size=20,
    )
    assert result == 2.0  # the recipe's own original quantity, untouched


def test_effective_ingredient_quantity_special_occasion_scaled_when_override_set():
    result = settings_service.effective_ingredient_quantity(
        2.0,
        recipe_servings=4,
        is_special_occasion=True,
        household_size_override=8,
        default_household_size=20,
    )
    assert result == 4.0  # scaled to the explicit per-day override, not left alone


def test_effective_ingredient_quantity_special_occasion_none_quantity_stays_none():
    result = settings_service.effective_ingredient_quantity(
        None,
        recipe_servings=4,
        is_special_occasion=True,
        household_size_override=None,
        default_household_size=20,
    )
    assert result is None
