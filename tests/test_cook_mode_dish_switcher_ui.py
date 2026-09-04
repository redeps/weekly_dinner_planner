"""
Milestone 16 Phase 4: Cook Mode's multi-dish switcher -- when a plan day
has attached sides/desserts (`plan_day_dishes`), a switcher lets you view
any of them (main included) without leaving Cook Mode, each with its own
independent step progress. A day with no attached dishes behaves exactly
as before this phase (tests/test_ingredient_scaling_ui.py already covers
that path in detail -- these tests focus on the switcher itself). Uses
streamlit.testing.v1 AppTest, same isolated-schema pattern as
tests/test_ingredient_scaling_ui.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.ingredients import replace_recipe_ingredients
from services.plan_generation import attach_dish
from services.recipes import create_recipe

REPO = Path(__file__).parent.parent
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


def make_recipe(conn, name, *, course="main", servings=4, quantity=2.0, instructions=None):
    recipe_id = create_recipe(
        conn,
        name=name,
        cook_time_minutes=20,
        family_enjoyment=3,
        seasonality="all-season",
        servings=servings,
        course=course,
        instructions=instructions or f"Step 1 for {name}.\nStep 2 for {name}.\nStep 3 for {name}.",
    )
    replace_recipe_ingredients(
        conn, recipe_id, [{"name": "Flour", "quantity": quantity, "unit": "cups", "store_category": "pantry"}]
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


def _load(**session_state):
    at = AppTest.from_file(COOK_MODE_PAGE)
    at.session_state["authenticated"] = True
    for key, value in session_state.items():
        at.session_state[key] = value
    return at.run()


def _switcher(at):
    matches = [sb for sb in at.selectbox if sb.key == "cook_mode_dish_switcher"]
    return matches[0] if matches else None


# --- no switcher when there's nothing to switch to ---


def test_no_switcher_when_day_has_no_attached_dishes(isolated_db):
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken")
    plan_day_id = make_plan_day(conn, main_id)
    conn.close()

    at = _load(selected_recipe_id=main_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    assert _switcher(at) is None
    assert "Step 1 for Roast Chicken." in [m.value.lstrip("# ") for m in at.markdown]


def test_no_switcher_when_reached_with_no_plan_day_at_all(isolated_db):
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken")
    conn.close()

    at = _load(selected_recipe_id=main_id)
    assert not at.exception
    assert _switcher(at) is None


# --- switcher shown, with the right options ---


def test_switcher_shown_with_main_and_attached_dishes(isolated_db):
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken")
    side_id = make_recipe(conn, "Garden Salad", course="side")
    dessert_id = make_recipe(conn, "Apple Crumble", course="dessert")
    plan_day_id = make_plan_day(conn, main_id)
    attach_dish(conn, plan_day_id, side_id)
    attach_dish(conn, plan_day_id, dessert_id)
    conn.close()

    at = _load(selected_recipe_id=main_id, selected_plan_day_id=plan_day_id)
    assert not at.exception
    switcher = _switcher(at)
    assert switcher is not None
    # `.options` on the AppTest proxy already reflects format_func's output.
    assert set(switcher.options) == {"Main: Roast Chicken", "Side: Garden Salad", "Dessert: Apple Crumble"}
    assert switcher.value == main_id  # defaults to the entry recipe


# --- switching shows the chosen dish's own steps and ingredients ---


def test_switching_to_a_dish_shows_its_own_steps(isolated_db):
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken")
    side_id = make_recipe(conn, "Garden Salad", course="side")
    plan_day_id = make_plan_day(conn, main_id)
    attach_dish(conn, plan_day_id, side_id)
    conn.close()

    at = _load(selected_recipe_id=main_id, selected_plan_day_id=plan_day_id)
    at = _switcher(at).set_value(side_id).run()

    assert not at.exception
    assert at.caption[0].value == "Garden Salad"
    assert "Step 1 for Garden Salad." in [m.value.lstrip("# ") for m in at.markdown]


def test_attached_dish_ingredients_scale_like_the_main(isolated_db):
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken", servings=4, quantity=2.0)
    side_id = make_recipe(conn, "Garden Salad", course="side", servings=4, quantity=2.0)
    plan_day_id = make_plan_day(conn, main_id, household_size_override=8)
    attach_dish(conn, plan_day_id, side_id)
    conn.close()

    at = _load(selected_recipe_id=main_id, selected_plan_day_id=plan_day_id)
    at = _switcher(at).set_value(side_id).run()

    assert not at.exception
    assert any("4 cups Flour" in m.value for m in at.markdown)  # 2.0 * (8/4)
    assert "Originally serves 4, scaled to 8." in [c.value for c in at.caption]


# --- independent per-dish step progress ---


def test_switching_between_dishes_preserves_independent_step_progress(isolated_db):
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken")
    side_id = make_recipe(conn, "Garden Salad", course="side")
    plan_day_id = make_plan_day(conn, main_id)
    attach_dish(conn, plan_day_id, side_id)
    conn.close()

    at = _load(selected_recipe_id=main_id, selected_plan_day_id=plan_day_id)

    # Advance the main to step 2.
    at = [b for b in at.button if b.label == "Next →"][0].click().run()
    assert "Step 2 of 3" in [c.value for c in at.caption]

    # Switch to the side -- must start at its own step 1, not carry the
    # main's step 2 over.
    at = _switcher(at).set_value(side_id).run()
    assert "Step 1 of 3" in [c.value for c in at.caption]

    # Advance the side to step 2 as well, independently.
    at = [b for b in at.button if b.label == "Next →"][0].click().run()
    assert "Step 2 of 3" in [c.value for c in at.caption]
    assert "Step 2 for Garden Salad." in [m.value.lstrip("# ") for m in at.markdown]

    # Switch back to the main -- its own step 2 progress must still be there.
    at = _switcher(at).set_value(main_id).run()
    assert "Step 2 of 3" in [c.value for c in at.caption]
    assert "Step 2 for Roast Chicken." in [m.value.lstrip("# ") for m in at.markdown]


def test_reopening_for_a_different_day_resets_step_progress(isolated_db):
    """A fresh entry (different plan_day) must not inherit stale step
    progress left over from a previous visit."""
    conn = database.get_connection()
    main_id = make_recipe(conn, "Roast Chicken")
    plan_day_id_1 = make_plan_day(conn, main_id)
    plan_day_id_2 = make_plan_day(conn, main_id)
    conn.close()

    at = _load(selected_recipe_id=main_id, selected_plan_day_id=plan_day_id_1)
    at = [b for b in at.button if b.label == "Next →"][0].click().run()
    assert "Step 2 of 3" in [c.value for c in at.caption]

    # Same session, but now pointed at a different day (as Week Plan's
    # own "Cook" button would do for a fresh click) -- must not carry the
    # previous day's step progress over.
    at.session_state["selected_plan_day_id"] = plan_day_id_2
    at = at.run()
    assert "Step 1 of 3" in [c.value for c in at.caption]
