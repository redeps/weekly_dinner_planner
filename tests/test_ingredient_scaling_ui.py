"""
Household-size ingredient-scaling on Recipe Detail and Cook Mode
(docs/DECISIONS.md — "Ingredient scaling extended to Recipe Detail and
Cook Mode"). Drives the real page scripts via AppTest, same isolated-
schema pattern as tests/test_household_scaling_ui.py.

Covers: day-scoped vs. generic-browsing display, the stale/mismatched
plan_day_id guard, the day-context leak-prevention (view a day, then
browse generically, confirm no stale scaling survives), the special-
occasion scaling exemption, and the "not scaled" flag in Cook Mode.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.ingredients import replace_recipe_ingredients
from services.recipes import create_recipe
from services.settings import set_default_household_size

REPO = Path(__file__).parent.parent
HOME_PAGE = str(REPO / "app.py")
RECIPE_DETAIL_PAGE = str(REPO / "pages" / "3_Recipe_Detail.py")
COOK_MODE_PAGE = str(REPO / "pages" / "8_Cook_Mode.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def make_recipe(conn, name="Recipe", servings=2, quantity=2.0, is_special_occasion=False):
    recipe_id = create_recipe(
        conn,
        name=name,
        cook_time_minutes=30,
        family_enjoyment=3,
        seasonality="all-season",
        servings=servings,
        is_special_occasion=is_special_occasion,
        instructions="Cook it.",
    )
    replace_recipe_ingredients(
        conn,
        recipe_id,
        [{"name": "Flour", "quantity": quantity, "unit": "cups", "store_category": "pantry"}],
    )
    return recipe_id


def make_plan_day(conn, recipe_id, *, household_size_override=None):
    week_plan_id = conn.execute(
        "INSERT INTO week_plans (week_start_date) VALUES ('2026-09-07') RETURNING id"
    ).fetchone()[0]
    plan_day_id = conn.execute(
        """
        INSERT INTO plan_days (
            week_plan_id, day_of_week, date, is_busy, dinner_ready_time, recipe_id,
            household_size_override
        )
        VALUES (%s, 'monday', '2026-09-07', 0, '18:00', %s, %s)
        RETURNING id
        """,
        (week_plan_id, recipe_id, household_size_override),
    ).fetchone()[0]
    conn.commit()
    return plan_day_id


def _load(page, **session_state):
    at = AppTest.from_file(page)
    at.session_state["authenticated"] = True
    for key, value in session_state.items():
        at.session_state[key] = value
    return at.run()


# --- Recipe Detail: day-scoped vs. generic browsing ---


def test_recipe_detail_shows_scaled_amount_and_caption_when_day_scoped(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, servings=2, quantity=2.0)
    plan_day_id = make_plan_day(conn, recipe_id, household_size_override=8)
    conn.close()

    at = _load(RECIPE_DETAIL_PAGE, selected_recipe_id=recipe_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert "Originally serves 2, scaled to 8." in [c.value for c in at.caption]
    assert any("8 cups Flour" in m.value for m in at.markdown)


def test_recipe_detail_shows_original_amount_when_reached_generically(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, servings=2, quantity=2.0)
    conn.close()

    at = _load(RECIPE_DETAIL_PAGE, selected_recipe_id=recipe_id)
    assert not at.exception
    assert not any("scaled to" in c.value for c in at.caption)
    assert any("2 cups Flour" in m.value for m in at.markdown)


def test_recipe_detail_ignores_mismatched_plan_day_id(isolated_db):
    """A plan_day_id pointing at a *different* recipe than the one being
    shown must not scale this recipe -- the stale-pointer guard."""
    conn = database.get_connection()
    recipe_a = make_recipe(conn, name="Recipe A", servings=2, quantity=2.0)
    recipe_b = make_recipe(conn, name="Recipe B", servings=2, quantity=2.0)
    plan_day_id = make_plan_day(conn, recipe_b, household_size_override=8)
    conn.close()

    # session points at recipe_a but carries a plan_day_id for recipe_b
    at = _load(RECIPE_DETAIL_PAGE, selected_recipe_id=recipe_a, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert not any("scaled to" in c.value for c in at.caption)
    assert any("2 cups Flour" in m.value for m in at.markdown), "must show recipe_a's own original amount, not recipe_b's scaled one"


# --- Day-context leak prevention (view a day, then browse generically) ---


def test_viewing_a_day_then_browsing_generically_does_not_leak_stale_scaling(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, name="Leak Test Recipe", servings=2, quantity=2.0)
    plan_day_id = make_plan_day(conn, recipe_id, household_size_override=8)
    conn.close()

    # Step 1: view the recipe from a specific day (Week Plan's "View"
    # sets both keys) -- confirms the scaled path itself works first.
    at = _load(RECIPE_DETAIL_PAGE, selected_recipe_id=recipe_id, selected_plan_day_id=plan_day_id)
    assert any("8 cups Flour" in m.value for m in at.markdown)

    # Step 2: browse generically via pages/1_Recipes.py, with the stale
    # plan_day_id still sitting in session state from step 1 -- clicking
    # "View" there must clear it, and the resulting Recipe Detail view
    # (reached via its own st.switch_page()) must show the original
    # amount, not the stale scaled one. st.switch_page() only resolves
    # correctly through AppTest when the session started from the real
    # entrypoint (app.py) -- see tests/test_polish_ui.py.
    home = AppTest.from_file(HOME_PAGE)
    home.session_state["authenticated"] = True
    home = home.run()
    home.session_state["selected_plan_day_id"] = plan_day_id
    at_recipes = home.switch_page("pages/1_Recipes.py").run()

    view_button = [b for b in at_recipes.button if b.key == f"view_{recipe_id}"][0]
    at_detail = view_button.click().run()

    assert not at_detail.exception
    assert "selected_plan_day_id" not in at_detail.session_state, (
        "generic browsing must clear the stale plan_day_id"
    )
    assert any("2 cups Flour" in m.value for m in at_detail.markdown)
    assert not any("8 cups Flour" in m.value for m in at_detail.markdown)


# --- Special-occasion scaling exemption ---


def test_special_occasion_recipe_unscaled_with_no_override(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, servings=2, quantity=2.0, is_special_occasion=True)
    set_default_household_size(conn, 20)  # a large default that would obviously show if wrongly applied
    plan_day_id = make_plan_day(conn, recipe_id, household_size_override=None)
    conn.close()

    at = _load(RECIPE_DETAIL_PAGE, selected_recipe_id=recipe_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert any("2 cups Flour" in m.value for m in at.markdown)
    assert any(
        "Special-occasion recipe" in c.value and "serves 2" in c.value for c in at.caption
    )


def test_special_occasion_recipe_scaled_when_override_set(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, servings=2, quantity=2.0, is_special_occasion=True)
    plan_day_id = make_plan_day(conn, recipe_id, household_size_override=6)
    conn.close()

    at = _load(RECIPE_DETAIL_PAGE, selected_recipe_id=recipe_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert any("6 cups Flour" in m.value for m in at.markdown)
    assert "Originally serves 2, scaled to 6." in [c.value for c in at.caption]


# --- Cook Mode: same scaling behavior, plus the "not scaled" flag ---


def test_cook_mode_shows_scaled_amount_when_day_scoped(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, servings=2, quantity=2.0)
    plan_day_id = make_plan_day(conn, recipe_id, household_size_override=8)
    conn.close()

    at = _load(COOK_MODE_PAGE, selected_recipe_id=recipe_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert any("8 cups Flour" in m.value for m in at.markdown)


def test_cook_mode_shows_original_amount_when_reached_generically(isolated_db):
    conn = database.get_connection()
    recipe_id = make_recipe(conn, servings=2, quantity=2.0)
    conn.close()

    at = _load(COOK_MODE_PAGE, selected_recipe_id=recipe_id)
    assert not at.exception
    assert any("2 cups Flour" in m.value for m in at.markdown)


def test_cook_mode_flags_unscaled_row_with_no_quantity(isolated_db):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name="Salt to Taste Recipe",
        cook_time_minutes=10,
        family_enjoyment=3,
        seasonality="all-season",
        servings=2,
        instructions="Season.",
    )
    replace_recipe_ingredients(
        conn, recipe_id, [{"name": "Salt", "quantity": None, "unit": None, "store_category": "pantry"}]
    )
    plan_day_id = make_plan_day(conn, recipe_id, household_size_override=8)
    conn.close()

    at = _load(COOK_MODE_PAGE, selected_recipe_id=recipe_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert any("not scaled" in m.value and "Salt" in m.value for m in at.markdown)
