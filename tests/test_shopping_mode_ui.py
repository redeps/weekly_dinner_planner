"""
Milestone 18 Phase 1: the Grocery List page's "Finish Shopping" action
and the empty-state gate it controls (pages/6_Grocery_List.py). Uses
streamlit.testing.v1 AppTest, same isolated-schema pattern as
tests/test_manual_grocery_items_ui.py.
"""

import datetime as dt
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.calendar import build_default_week_calendar
from services.ingredients import replace_recipe_ingredients
from services.plan_generation import generate_week_plan, get_week_plan
from services.recipes import create_recipe
from services.shopping_mode import mark_shopping_completed

REPO = Path(__file__).parent.parent
GROCERY_LIST_PAGE = str(REPO / "pages" / "6_Grocery_List.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def make_week_plan(week_start="2026-08-31"):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name="Roast Chicken",
        cook_time_minutes=60,
        family_enjoyment=4,
        seasonality="all-season",
        servings=4,
    )
    replace_recipe_ingredients(
        conn, recipe_id, [{"name": "milk", "quantity": 200, "unit": "ml", "store_category": "dairy"}]
    )
    week_plan_id = generate_week_plan(
        conn, week_start_date=dt.date.fromisoformat(week_start), calendar=build_default_week_calendar()
    )
    conn.close()
    return week_plan_id


def _load() -> AppTest:
    at = AppTest.from_file(GROCERY_LIST_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


def test_normal_week_shows_the_list_and_finish_shopping_button(isolated_db):
    make_week_plan()
    at = _load()
    assert not at.exception
    assert at.dataframe  # the grocery table is rendered
    assert any(b.key == "finish_shopping" for b in at.button)
    assert not any("complete" in s.value.lower() for s in at.success)


def test_clicking_finish_shopping_marks_the_week_completed(isolated_db):
    week_plan_id = make_week_plan()
    at = _load()
    at = [b for b in at.button if b.key == "finish_shopping"][0].click().run()
    assert not at.exception

    conn = database.get_connection()
    week_plan = get_week_plan(conn, week_plan_id)
    conn.close()
    assert week_plan.shopping_completed_at is not None


def test_completed_week_shows_no_list_no_editor_no_export_no_finish_button(isolated_db):
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    mark_shopping_completed(conn, week_plan_id)
    conn.close()

    at = _load()
    assert not at.exception
    assert any("complete" in s.value.lower() for s in at.success)
    assert not at.dataframe
    assert not any(b.key == "finish_shopping" for b in at.button)
    assert not at.download_button


def test_completed_week_still_shows_manual_item_sections(isolated_db):
    """Finish Shopping only gates the aggregated list + export -- the
    manual-item paste-in/recurring sections are untouched in this phase."""
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    mark_shopping_completed(conn, week_plan_id)
    conn.close()

    at = _load()
    assert not at.exception
    assert any("Recurring items" in s.value for s in at.subheader)
    assert any(w.key == "recurring_paste_input" for w in at.text_area)


def test_a_new_week_plan_shows_a_normal_list_after_a_prior_week_was_completed(isolated_db):
    week_a = make_week_plan("2026-08-31")
    conn = database.get_connection()
    mark_shopping_completed(conn, week_a)
    conn.close()

    make_week_plan("2026-09-07")  # a second, newer week plan
    at = _load()
    assert not at.exception
    assert at.dataframe  # the new (latest) week's list renders normally
    assert not any("complete" in s.value.lower() for s in at.success)
    assert any(b.key == "finish_shopping" for b in at.button)
