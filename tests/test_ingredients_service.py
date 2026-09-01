"""
Milestone 2 tests: ingredient service functions (services/ingredients.py).

Uses an isolated per-test Postgres schema — never touches the `public`
schema. See docs/DECISIONS.md — Milestone 13 hosting architecture.
"""

import psycopg
import pytest

import database
from services import ingredients as ingredient_service
from services import recipes as recipe_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


@pytest.fixture
def recipe_id(conn):
    return recipe_service.create_recipe(
        conn,
        name="Chicken Curry",
        cook_time_minutes=30,
        family_enjoyment=4,
        seasonality="winter",
        servings=4,
    )


def test_list_ingredients_empty_by_default(conn, recipe_id):
    assert ingredient_service.list_ingredients(conn, recipe_id) == []


def test_replace_recipe_ingredients_inserts_rows(conn, recipe_id):
    ingredient_service.replace_recipe_ingredients(
        conn,
        recipe_id,
        [
            {"name": "chicken thighs", "quantity": 500, "unit": "g", "store_category": "meat"},
            {"name": "onion", "quantity": 1, "unit": "each", "store_category": "produce"},
        ],
    )
    rows = ingredient_service.list_ingredients(conn, recipe_id)
    assert [r.name for r in rows] == ["chicken thighs", "onion"]
    assert rows[0].quantity == 500
    assert rows[0].unit == "g"
    assert rows[0].store_category == "meat"


def test_replace_recipe_ingredients_allows_missing_quantity_and_unit(conn, recipe_id):
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "salt to taste", "store_category": "pantry"}]
    )
    rows = ingredient_service.list_ingredients(conn, recipe_id)
    assert rows[0].quantity is None
    assert rows[0].unit is None


def test_replace_recipe_ingredients_defaults_store_category_to_other(conn, recipe_id):
    ingredient_service.replace_recipe_ingredients(conn, recipe_id, [{"name": "mystery item"}])
    rows = ingredient_service.list_ingredients(conn, recipe_id)
    assert rows[0].store_category == "other"


def test_replace_recipe_ingredients_rejects_invalid_store_category(conn, recipe_id):
    with pytest.raises(ValueError):
        ingredient_service.replace_recipe_ingredients(
            conn, recipe_id, [{"name": "mystery item", "store_category": "not-a-category"}]
        )


def test_replace_recipe_ingredients_invalid_row_leaves_existing_rows_untouched(conn, recipe_id):
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "onion", "store_category": "produce"}]
    )
    with pytest.raises(ValueError):
        ingredient_service.replace_recipe_ingredients(
            conn, recipe_id, [{"name": "mystery item", "store_category": "not-a-category"}]
        )
    rows = ingredient_service.list_ingredients(conn, recipe_id)
    assert [r.name for r in rows] == ["onion"]


def test_replace_recipe_ingredients_replaces_wholesale(conn, recipe_id):
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "onion", "store_category": "produce"}]
    )
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "garlic", "store_category": "produce"}]
    )
    rows = ingredient_service.list_ingredients(conn, recipe_id)
    assert [r.name for r in rows] == ["garlic"]


def test_replace_recipe_ingredients_with_empty_list_clears_all(conn, recipe_id):
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "onion", "store_category": "produce"}]
    )
    ingredient_service.replace_recipe_ingredients(conn, recipe_id, [])
    assert ingredient_service.list_ingredients(conn, recipe_id) == []


def test_replace_recipe_ingredients_db_failure_partway_through_reinsert_leaves_original_intact(
    conn, recipe_id
):
    """The Python-level store_category check
    (test_replace_recipe_ingredients_invalid_row_leaves_existing_rows_untouched,
    above) never reaches the database at all, so it can't prove the
    delete-all-then-reinsert sequence is transactionally atomic. This test
    forces a failure the database itself raises (a NOT NULL violation, not
    caught by _validate_store_category) partway through the reinsert loop
    — proving services/ingredients.py's `with conn.transaction():` wrap
    (see docs/DECISIONS.md) rolls back the whole delete+reinsert, not just
    the one bad row, under autocommit=True."""
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "onion", "store_category": "produce"}]
    )

    with pytest.raises(psycopg.Error):
        ingredient_service.replace_recipe_ingredients(
            conn,
            recipe_id,
            [
                {"name": "garlic", "store_category": "produce"},
                {"name": None, "store_category": "produce"},  # violates NOT NULL at the DB
                {"name": "carrot", "store_category": "produce"},
            ],
        )

    rows = ingredient_service.list_ingredients(conn, recipe_id)
    assert [r.name for r in rows] == ["onion"], (
        "a DB failure partway through the reinsert must leave the original "
        "ingredients intact, not a partial or empty set"
    )


def test_replace_recipe_ingredients_only_affects_its_own_recipe(conn, recipe_id):
    other_recipe_id = recipe_service.create_recipe(
        conn,
        name="Tacos",
        cook_time_minutes=20,
        family_enjoyment=5,
        seasonality="all-season",
        servings=4,
    )
    ingredient_service.replace_recipe_ingredients(
        conn, recipe_id, [{"name": "onion", "store_category": "produce"}]
    )
    ingredient_service.replace_recipe_ingredients(
        conn, other_recipe_id, [{"name": "tortillas", "store_category": "pantry"}]
    )
    assert [r.name for r in ingredient_service.list_ingredients(conn, recipe_id)] == ["onion"]
    assert [r.name for r in ingredient_service.list_ingredients(conn, other_recipe_id)] == [
        "tortillas"
    ]
