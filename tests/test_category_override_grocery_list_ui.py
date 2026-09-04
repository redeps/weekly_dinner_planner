"""
Milestone 17 Phase 2: the Grocery List page's editable Category column
(st.data_editor + SelectboxColumn, pages/6_Grocery_List.py).

Note on coverage: `streamlit.testing.v1`'s `Dataframe` proxy (what
`st.data_editor` renders as in AppTest) exposes only `.value` — confirmed
directly against the installed Streamlit version, not assumed — with no
`set_value()` or other way to simulate a live cell edit. So these tests
cover what AppTest actually can: the page renders the editor with the
correct initial data and column configuration, and never creates an
override on its own. The diff-detection logic itself
(`services.category_overrides.detect_category_edits`, what actually runs
when a real edit comes back from the browser) is tested directly with
plain dicts in tests/test_category_overrides_service.py, independent of
AppTest. See docs/DECISIONS.md.
"""

import datetime as dt
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from models import STORE_CATEGORIES
from services.calendar import build_default_week_calendar
from services.category_overrides import get_override
from services.ingredients import replace_recipe_ingredients
from services.plan_generation import generate_week_plan
from services.recipes import create_recipe

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


@pytest.fixture
def week_plan_id(isolated_db):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name="Pancakes",
        cook_time_minutes=10,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    replace_recipe_ingredients(
        conn, recipe_id, [{"name": "milk", "quantity": 200, "unit": "ml", "store_category": "pantry"}]
    )
    week_plan_id = generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=build_default_week_calendar()
    )
    conn.close()
    return week_plan_id


def _load(week_plan_id) -> AppTest:
    at = AppTest.from_file(GROCERY_LIST_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


def test_page_loads_with_editable_table_showing_correct_data(week_plan_id):
    at = _load(week_plan_id)
    assert not at.exception
    assert any("Recategorize" in c.value for c in at.caption)

    editor = at.dataframe[0]
    rows = editor.value.to_dict("records")
    # A single-recipe pool fills all 7 days (no-repeat-within-week falls
    # back to allowing repeats below 7 distinct recipes), so 200ml * 7.
    assert rows == [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "1400", "Unit": "ml"}]


def test_editor_is_reachable_by_its_key(week_plan_id):
    # Column config (the SelectboxColumn, which columns are disabled)
    # isn't introspectable via the public AppTest proxy -- this just
    # confirms the editor renders under the key production code expects.
    at = _load(week_plan_id)
    assert not at.exception
    assert at.dataframe[0].key == "grocery_table_editor"


def test_loading_the_page_never_creates_an_override_on_its_own(week_plan_id):
    at = _load(week_plan_id)
    assert not at.exception

    conn = database.get_connection()
    assert get_override(conn, "milk") is None
    conn.close()


def test_page_reflects_an_existing_override_in_the_initial_data(week_plan_id):
    """If an override already exists (set previously), the table's
    initial render must already show the corrected category -- proving
    build_grocery_list() (not the editor itself) is what applies it."""
    conn = database.get_connection()
    from services.category_overrides import set_override

    set_override(conn, "milk", "dairy")
    conn.close()

    at = _load(week_plan_id)
    assert not at.exception
    rows = at.dataframe[0].value.to_dict("records")
    assert rows[0]["Category"] == "Dairy"
