"""
"Generate New Plan" moved from Week Plan to Weekly Calendar (see
docs/DECISIONS.md — 2026-09-04). Confirms the button's new location, that
Week Plan no longer offers one, and that clicking it generates a plan from
the calendar's current input and navigates to Week Plan — same
AppTest/isolated-schema pattern as tests/test_special_occasion_calendar_ui.py
and tests/test_household_scaling_ui.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.recipes import create_recipe

REPO = Path(__file__).parent.parent
HOME_PAGE = str(REPO / "app.py")
WEEKLY_CALENDAR_PAGE = str(REPO / "pages" / "4_Weekly_Calendar.py")
WEEK_PLAN_PAGE = str(REPO / "pages" / "5_Week_Plan.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


@pytest.fixture
def recipe_id(isolated_db):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name="Test Recipe",
        cook_time_minutes=20,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    conn.close()
    return recipe_id


# --- location ---


def test_weekly_calendar_has_generate_button(recipe_id):
    at = AppTest.from_file(WEEKLY_CALENDAR_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    assert not at.exception
    assert any(b.label == "Generate New Plan" for b in at.button)


def test_week_plan_has_no_generate_button(recipe_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    assert not at.exception
    assert not any(b.label == "Generate New Plan" for b in at.button)


def test_week_plan_empty_state_points_to_weekly_calendar(recipe_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    assert not at.exception
    assert any("Weekly Calendar" in info.value for info in at.info)


# --- clicking it generates and navigates ---


def test_clicking_generate_creates_a_plan_and_navigates_to_week_plan(recipe_id):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    at = [b for b in at.button if b.label == "Generate New Plan"][0].click().run()

    assert not at.exception
    assert at.title[0].value == "Week Plan"
    assert len(at.caption) > 0
    assert any(cap.value.startswith("Week of ") for cap in at.caption)


def test_generated_plan_carries_current_calendar_input(recipe_id):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    at.checkbox(key="cal_busy_wednesday").set_value(True)
    at = at.run()

    at = [b for b in at.button if b.label == "Generate New Plan"][0].click().run()
    assert not at.exception
    assert at.title[0].value == "Week Plan"

    from database import get_connection
    from services.plan_generation import get_latest_week_plan, list_plan_days

    conn = get_connection()
    week_plan = get_latest_week_plan(conn)
    plan_days = {d.day_of_week: d for d in list_plan_days(conn, week_plan.id)}
    conn.close()

    assert plan_days["wednesday"].is_busy is True
    assert plan_days["monday"].is_busy is False


def test_generate_with_no_recipes_shows_error_and_does_not_navigate(isolated_db):
    # Loaded directly (not via Home), so app.py's own quick-fallback-recipe
    # seeding (in main()) never runs and the recipe pool stays genuinely
    # empty — reproduces generate_week_plan()'s "No active, non-special-
    # occasion recipes" ValueError.
    at = AppTest.from_file(WEEKLY_CALENDAR_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()

    at = [b for b in at.button if b.label == "Generate New Plan"][0].click().run()

    assert not at.exception
    assert at.title[0].value == "Weekly Calendar"
    assert len(at.error) == 1
