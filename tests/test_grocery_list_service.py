"""
Milestone 6 tests: grocery list aggregation (services/grocery_list.py).
"""

import pytest

import database
from services import grocery_list as grocery_service
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


def make_recipe(conn, name="Recipe", ingredients=None, servings=4):
    recipe_id = recipe_service.create_recipe(
        conn,
        name=name,
        cook_time_minutes=30,
        family_enjoyment=3,
        seasonality="all-season",
        servings=servings,
    )
    if ingredients:
        ingredient_service.replace_recipe_ingredients(conn, recipe_id, ingredients)
    return recipe_id


def make_week_plan(conn, day_recipe_pairs, week_start="2026-08-31", household_size_overrides=None):
    """day_recipe_pairs: list of (day_of_week, recipe_id_or_None).
    household_size_overrides: optional dict of day_of_week -> override size,
    for days not in the dict `household_size_override` stays NULL."""
    household_size_overrides = household_size_overrides or {}
    week_plan_id = conn.execute(
        "INSERT INTO week_plans (week_start_date) VALUES (%s) RETURNING id", (week_start,)
    ).fetchone()[0]
    for i, (day_of_week, recipe_id) in enumerate(day_recipe_pairs):
        conn.execute(
            """
            INSERT INTO plan_days (
                week_plan_id, day_of_week, date, is_busy, dinner_ready_time, recipe_id,
                household_size_override
            )
            VALUES (%s, %s, %s, 0, '18:00', %s, %s)
            """,
            (
                week_plan_id,
                day_of_week,
                f"2026-08-{i + 1:02d}",
                recipe_id,
                household_size_overrides.get(day_of_week),
            ),
        )
    conn.commit()
    return week_plan_id


def test_build_grocery_list_empty_when_no_plan_days(conn):
    week_plan_id = make_week_plan(conn, [])
    assert grocery_service.build_grocery_list(conn, week_plan_id) == {}


def test_build_grocery_list_empty_for_nonexistent_week_plan(conn):
    assert grocery_service.build_grocery_list(conn, 999) == {}


def test_build_grocery_list_sums_matching_name_and_unit_across_recipes(conn):
    recipe_a = make_recipe(
        conn, "Recipe A", [{"name": "flour", "quantity": 200, "unit": "g", "store_category": "pantry"}]
    )
    recipe_b = make_recipe(
        conn, "Recipe B", [{"name": "flour", "quantity": 300, "unit": "g", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe_a), ("tuesday", recipe_b)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert [item.name for item in result["pantry"]] == ["flour"]
    assert result["pantry"][0].quantity == 500
    assert result["pantry"][0].unit == "g"


def test_build_grocery_list_keeps_different_units_separate(conn):
    recipe_a = make_recipe(
        conn, "Recipe A", [{"name": "flour", "quantity": 200, "unit": "g", "store_category": "pantry"}]
    )
    recipe_b = make_recipe(
        conn, "Recipe B", [{"name": "flour", "quantity": 2, "unit": "cups", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe_a), ("tuesday", recipe_b)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert len(result["pantry"]) == 2
    by_unit = {item.unit: item.quantity for item in result["pantry"]}
    assert by_unit == {"g": 200, "cups": 2}


def test_build_grocery_list_doubles_when_recipe_repeats_within_week(conn):
    recipe = make_recipe(
        conn, "Chili", [{"name": "flour", "quantity": 200, "unit": "g", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe), ("thursday", recipe)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert result["pantry"][0].quantity == 400


def test_build_grocery_list_normalizes_name_and_unit_casing_and_whitespace(conn):
    recipe_a = make_recipe(
        conn, "A", [{"name": "  Flour", "quantity": 100, "unit": "G", "store_category": "pantry"}]
    )
    recipe_b = make_recipe(
        conn, "B", [{"name": "FLOUR ", "quantity": 150, "unit": " g", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe_a), ("tuesday", recipe_b)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert len(result["pantry"]) == 1
    assert result["pantry"][0].quantity == 250
    # display name/unit come from the first entry seen
    assert result["pantry"][0].name == "Flour"
    assert result["pantry"][0].unit == "G"


def test_build_grocery_list_handles_missing_quantity_without_duplicating(conn):
    recipe = make_recipe(
        conn, "Chili", [{"name": "salt to taste", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe), ("thursday", recipe)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert len(result["pantry"]) == 1
    assert result["pantry"][0].quantity is None


def test_build_grocery_list_groups_by_store_category(conn):
    recipe = make_recipe(
        conn,
        "Mixed",
        [
            {"name": "onion", "quantity": 1, "unit": "each", "store_category": "produce"},
            {"name": "chicken", "quantity": 500, "unit": "g", "store_category": "meat"},
        ],
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert set(result.keys()) == {"produce", "meat"}
    assert result["produce"][0].name == "onion"
    assert result["meat"][0].name == "chicken"


def test_build_grocery_list_omits_empty_categories(conn):
    recipe = make_recipe(
        conn, "Simple", [{"name": "onion", "quantity": 1, "unit": "each", "store_category": "produce"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert "dairy" not in result
    assert "frozen" not in result


def test_build_grocery_list_skips_days_with_no_recipe_assigned(conn):
    week_plan_id = make_week_plan(conn, [("monday", None)])
    assert grocery_service.build_grocery_list(conn, week_plan_id) == {}


def test_build_grocery_list_ignores_quick_fallback_recipes_with_no_ingredients(conn):
    recipe = make_recipe(conn, "Takeout")  # no ingredients
    week_plan_id = make_week_plan(conn, [("monday", recipe)])
    assert grocery_service.build_grocery_list(conn, week_plan_id) == {}


def test_build_grocery_list_scales_quantity_by_day_household_size_override(conn):
    recipe = make_recipe(  # servings=4
        conn, "Chili", [{"name": "flour", "quantity": 200, "unit": "g", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(
        conn, [("monday", recipe)], household_size_overrides={"monday": 8}
    )
    result = grocery_service.build_grocery_list(conn, week_plan_id)
    assert result["pantry"][0].quantity == 400


def test_build_grocery_list_uses_global_default_when_no_override(conn):
    from services.settings import set_default_household_size

    set_default_household_size(conn, 8)
    recipe = make_recipe(  # servings=4
        conn, "Chili", [{"name": "flour", "quantity": 200, "unit": "g", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe)])
    result = grocery_service.build_grocery_list(conn, week_plan_id)
    assert result["pantry"][0].quantity == 400


def test_build_grocery_list_unchanged_when_household_size_equals_servings(conn):
    from services.settings import DEFAULT_HOUSEHOLD_SIZE

    recipe = make_recipe(
        conn,
        "Chili",
        [{"name": "flour", "quantity": 200, "unit": "g", "store_category": "pantry"}],
        servings=DEFAULT_HOUSEHOLD_SIZE,
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe)])
    result = grocery_service.build_grocery_list(conn, week_plan_id)
    assert result["pantry"][0].quantity == 200


def test_build_grocery_list_rounds_scaled_quantity_to_two_decimals(conn):
    from services.settings import DEFAULT_HOUSEHOLD_SIZE

    recipe = make_recipe(
        conn, "Lasagne", [{"name": "olive oil", "quantity": 1, "unit": "tbsp", "store_category": "pantry"}],
        servings=6,
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe)])  # default size 4 -> 4/6
    result = grocery_service.build_grocery_list(conn, week_plan_id)
    assert result["pantry"][0].quantity == round(1 * (DEFAULT_HOUSEHOLD_SIZE / 6), 2)
    assert result["pantry"][0].quantity == 0.67


def test_build_grocery_list_sums_scaled_quantities_across_different_household_sizes(conn):
    # Mirrors real imported-recipe data: same ingredient across recipes with
    # different servings and different effective household sizes for the day.
    recipe_a = make_recipe(
        conn, "A", [{"name": "olive oil", "quantity": 1, "unit": "tbsp", "store_category": "pantry"}],
        servings=4,
    )
    recipe_b = make_recipe(
        conn, "B", [{"name": "olive oil", "quantity": 1, "unit": "tbsp", "store_category": "pantry"}],
        servings=6,
    )
    recipe_c = make_recipe(
        conn, "C", [{"name": "olive oil", "quantity": 2, "unit": "tbsp", "store_category": "pantry"}],
        servings=4,
    )
    recipe_d = make_recipe(
        conn, "D", [{"name": "olive oil", "quantity": 2, "unit": "tbsp", "store_category": "pantry"}],
        servings=4,
    )
    week_plan_id = make_week_plan(
        conn,
        [("monday", recipe_a), ("tuesday", recipe_b), ("wednesday", recipe_c), ("thursday", recipe_d)],
        household_size_overrides={"monday": 6, "thursday": 5},  # tuesday/wednesday use default (4)
    )
    result = grocery_service.build_grocery_list(conn, week_plan_id)
    # 1*(6/4) + 1*(4/6) + 2*(4/4) + 2*(5/4), each rounded to 2dp before summing
    assert result["pantry"][0].quantity == 6.67


def test_build_grocery_list_missing_quantity_stays_unscaled_regardless_of_household_size(conn):
    recipe = make_recipe(
        conn, "Chili", [{"name": "salt to taste", "store_category": "pantry"}]
    )
    week_plan_id = make_week_plan(
        conn, [("monday", recipe)], household_size_overrides={"monday": 10}
    )
    result = grocery_service.build_grocery_list(conn, week_plan_id)
    assert result["pantry"][0].quantity is None


def test_build_grocery_list_sorts_items_alphabetically_within_category(conn):
    recipe = make_recipe(
        conn,
        "Mixed",
        [
            {"name": "zucchini", "quantity": 1, "unit": "each", "store_category": "produce"},
            {"name": "apple", "quantity": 1, "unit": "each", "store_category": "produce"},
        ],
    )
    week_plan_id = make_week_plan(conn, [("monday", recipe)])

    result = grocery_service.build_grocery_list(conn, week_plan_id)

    assert [item.name for item in result["produce"]] == ["apple", "zucchini"]
