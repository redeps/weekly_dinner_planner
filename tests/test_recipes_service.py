"""
Milestone 1 tests: recipe service functions (services/recipes.py).

Uses an isolated per-test Postgres schema — never touches the `public`
schema. See docs/DECISIONS.md — Milestone 13 hosting architecture.
"""

import pytest

import database
from services import recipes as recipe_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def make_recipe(conn, **overrides):
    fields = {
        "name": "Chicken Curry",
        "cook_time_minutes": 30,
        "family_enjoyment": 4,
        "seasonality": "winter",
        "servings": 4,
        "instructions": "Cook it.",
        "notes": "Spicy.",
    }
    fields.update(overrides)
    return recipe_service.create_recipe(conn, **fields)


def test_create_recipe_returns_id(conn):
    recipe_id = make_recipe(conn)
    assert isinstance(recipe_id, int)
    assert recipe_id > 0


def test_create_recipe_rejects_invalid_seasonality(conn):
    with pytest.raises(ValueError):
        make_recipe(conn, seasonality="not-a-season")


def test_create_recipe_defaults_course_to_main(conn):
    recipe_id = make_recipe(conn)
    recipe = recipe_service.get_recipe(conn, recipe_id)
    assert recipe.course == "main"


def test_create_recipe_accepts_side_and_dessert_courses(conn):
    side_id = make_recipe(conn, name="Salad", course="side")
    dessert_id = make_recipe(conn, name="Crumble", course="dessert")
    assert recipe_service.get_recipe(conn, side_id).course == "side"
    assert recipe_service.get_recipe(conn, dessert_id).course == "dessert"


def test_create_recipe_rejects_invalid_course(conn):
    with pytest.raises(ValueError):
        make_recipe(conn, course="starter")


def test_get_recipe_returns_recipe(conn):
    recipe_id = make_recipe(conn, name="Tacos")
    recipe = recipe_service.get_recipe(conn, recipe_id)
    assert recipe is not None
    assert recipe.name == "Tacos"
    assert recipe.active is True
    assert recipe.is_quick_fallback is False


def test_get_recipe_returns_none_for_missing_id(conn):
    assert recipe_service.get_recipe(conn, 999) is None


def test_update_recipe_changes_fields(conn):
    recipe_id = make_recipe(conn, name="Tacos")
    recipe_service.update_recipe(conn, recipe_id, name="Beef Tacos", cook_time_minutes=25)
    recipe = recipe_service.get_recipe(conn, recipe_id)
    assert recipe.name == "Beef Tacos"
    assert recipe.cook_time_minutes == 25


def test_update_recipe_rejects_invalid_seasonality(conn):
    recipe_id = make_recipe(conn)
    with pytest.raises(ValueError):
        recipe_service.update_recipe(conn, recipe_id, seasonality="nope")


def test_update_recipe_changes_course(conn):
    recipe_id = make_recipe(conn)
    recipe_service.update_recipe(conn, recipe_id, course="dessert")
    recipe = recipe_service.get_recipe(conn, recipe_id)
    assert recipe.course == "dessert"


def test_update_recipe_rejects_invalid_course(conn):
    recipe_id = make_recipe(conn)
    with pytest.raises(ValueError):
        recipe_service.update_recipe(conn, recipe_id, course="starter")


def test_update_recipe_noop_with_no_fields(conn):
    recipe_id = make_recipe(conn, name="Tacos")
    recipe_service.update_recipe(conn, recipe_id)
    recipe = recipe_service.get_recipe(conn, recipe_id)
    assert recipe.name == "Tacos"


def test_list_recipes_excludes_inactive_by_default(conn):
    recipe_id = make_recipe(conn, name="Tacos")
    recipe_service.deactivate_recipe(conn, recipe_id)
    assert recipe_service.list_recipes(conn) == []
    assert len(recipe_service.list_recipes(conn, include_inactive=True)) == 1


def test_list_recipes_search_is_case_insensitive_substring(conn):
    make_recipe(conn, name="Chicken Curry")
    make_recipe(conn, name="Beef Tacos")
    results = recipe_service.list_recipes(conn, search="chicken")
    assert [r.name for r in results] == ["Chicken Curry"]


def test_list_recipes_filters_by_season(conn):
    make_recipe(conn, name="Winter Stew", seasonality="winter")
    make_recipe(conn, name="Summer Salad", seasonality="summer")
    make_recipe(conn, name="Pasta", seasonality="all-season")
    results = recipe_service.list_recipes(conn, season="winter")
    assert [r.name for r in results] == ["Winter Stew"]


def test_list_recipes_filters_quick_fallback_only(conn):
    make_recipe(conn, name="Chicken Curry")
    make_recipe(conn, name="Frozen Pizza", is_quick_fallback=True)
    results = recipe_service.list_recipes(conn, quick_fallback_only=True)
    assert [r.name for r in results] == ["Frozen Pizza"]


def test_list_recipes_filters_special_occasion_only(conn):
    make_recipe(conn, name="Chicken Curry")
    make_recipe(conn, name="Holiday Roast", is_special_occasion=True)
    results = recipe_service.list_recipes(conn, special_occasion_only=True)
    assert [r.name for r in results] == ["Holiday Roast"]


def test_list_recipes_filters_by_course(conn):
    make_recipe(conn, name="Chicken Curry")
    make_recipe(conn, name="Garden Salad", course="side")
    make_recipe(conn, name="Apple Crumble", course="dessert")
    results = recipe_service.list_recipes(conn, course="side")
    assert [r.name for r in results] == ["Garden Salad"]


def test_list_recipes_ordered_by_name(conn):
    make_recipe(conn, name="Zucchini Bake")
    make_recipe(conn, name="Apple Crumble")
    results = recipe_service.list_recipes(conn)
    assert [r.name for r in results] == ["Apple Crumble", "Zucchini Bake"]


def test_deactivate_recipe_marks_inactive(conn):
    recipe_id = make_recipe(conn)
    recipe_service.deactivate_recipe(conn, recipe_id)
    recipe = recipe_service.get_recipe(conn, recipe_id)
    assert recipe.active is False


def test_seed_quick_fallback_recipes_inserts_seeds(conn):
    recipe_service.seed_quick_fallback_recipes(conn)
    results = recipe_service.list_recipes(conn, quick_fallback_only=True)
    assert {r.name for r in results} == {"Fish Fingers", "Frozen Pizza", "Takeout"}


def test_seed_quick_fallback_recipes_is_idempotent(conn):
    recipe_service.seed_quick_fallback_recipes(conn)
    recipe_service.seed_quick_fallback_recipes(conn)
    results = recipe_service.list_recipes(conn, quick_fallback_only=True)
    assert len(results) == 3
