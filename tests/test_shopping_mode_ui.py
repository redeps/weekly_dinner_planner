"""
Milestone 18: the Grocery List page's "Finish Shopping" action and the
empty-state gate it controls (Phase 1), plus "Start Shopping"'s checkbox
view, checked-off expander, and Restore (Phase 2) —
pages/6_Grocery_List.py. Uses streamlit.testing.v1 AppTest, same
isolated-schema pattern as tests/test_manual_grocery_items_ui.py.
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
from services.shopping_mode import check_item, list_checked_items, mark_shopping_completed

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
        conn,
        recipe_id,
        [
            {"name": "milk", "quantity": 200, "unit": "ml", "store_category": "dairy"},
            {"name": "flour", "quantity": 100, "unit": "g", "store_category": "pantry"},
        ],
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


# --- Phase 2: Start Shopping, checkbox view, checked-off expander, Restore ---


def _enter_shopping_mode(at: AppTest) -> AppTest:
    return [b for b in at.button if b.key == "start_shopping"][0].click().run()


def _shopping_editor(at: AppTest):
    return [d for d in at.dataframe if d.key == "grocery_table_editor_shopping"][0]


def test_start_shopping_shows_checkbox_editor_and_empty_checked_off_expander(isolated_db):
    make_week_plan()
    at = _load()
    at = _enter_shopping_mode(at)
    assert not at.exception
    assert any(b.key == "stop_shopping" for b in at.button)
    editor = _shopping_editor(at)
    assert list(editor.value["Checked"]) == [False, False]
    assert any(e.label == "Checked off (0)" for e in at.expander)


def test_checked_item_is_excluded_from_active_editor_and_listed_in_expander(isolated_db):
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    check_item(conn, week_plan_id, "milk", "ml")
    conn.close()

    at = _load()
    at = _enter_shopping_mode(at)
    assert not at.exception

    editor = _shopping_editor(at)
    assert "Milk" not in list(editor.value["Ingredient"])
    assert any(e.label == "Checked off (1)" for e in at.expander)
    assert any("Milk" in m.value for m in at.markdown)


def test_restoring_a_checked_item_unchecks_it_and_returns_it_to_the_active_editor(isolated_db):
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    check_item(conn, week_plan_id, "milk", "ml")
    conn.close()

    at = _load()
    at = _enter_shopping_mode(at)
    restore_buttons = [b for b in at.button if b.key.startswith("restore_")]
    assert len(restore_buttons) == 1

    at = restore_buttons[0].click().run()
    assert not at.exception

    conn = database.get_connection()
    assert list_checked_items(conn, week_plan_id) == []
    conn.close()

    editor = _shopping_editor(at)
    assert "Milk" in list(editor.value["Ingredient"])
    assert any(e.label == "Checked off (0)" for e in at.expander)


def test_checked_state_persists_across_a_fresh_session(isolated_db):
    """The actual point of the feature: a checked item set via one
    session must be visible from a brand-new AppTest/page load, not a
    continuation of the same session -- confirming state is DB-backed,
    not session-state-backed (only the Start/Stop Shopping toggle is)."""
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    check_item(conn, week_plan_id, "milk", "ml")
    conn.close()

    fresh_at = AppTest.from_file(GROCERY_LIST_PAGE)
    fresh_at.session_state["authenticated"] = True
    fresh_at = fresh_at.run()
    fresh_at = _enter_shopping_mode(fresh_at)
    assert not fresh_at.exception

    editor = _shopping_editor(fresh_at)
    assert "Milk" not in list(editor.value["Ingredient"])
    assert any(e.label == "Checked off (1)" for e in fresh_at.expander)


def test_finish_shopping_still_works_with_checked_items_present(isolated_db):
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    check_item(conn, week_plan_id, "milk", "ml")
    conn.close()

    at = _load()
    at = _enter_shopping_mode(at)
    at = [b for b in at.button if b.key == "finish_shopping"][0].click().run()
    assert not at.exception

    conn = database.get_connection()
    week_plan = get_week_plan(conn, week_plan_id)
    checked = list_checked_items(conn, week_plan_id)
    conn.close()
    assert week_plan.shopping_completed_at is not None
    assert checked == [("milk", "ml")], "checked items are not cleaned up on completion"


def test_a_completed_weeks_checked_items_do_not_appear_in_a_new_weeks_view(isolated_db):
    week_a = make_week_plan("2026-08-31")
    conn = database.get_connection()
    check_item(conn, week_a, "milk", "ml")
    mark_shopping_completed(conn, week_a)
    conn.close()

    make_week_plan("2026-09-07")
    at = _load()
    at = _enter_shopping_mode(at)
    assert not at.exception
    editor = _shopping_editor(at)
    assert "Milk" in list(editor.value["Ingredient"])  # not pre-checked in the new week
    assert any(e.label == "Checked off (0)" for e in at.expander)


def test_checking_off_everything_shows_a_message_instead_of_an_empty_editor(isolated_db):
    """st.data_editor([]) renders with no columns at all -- a real edge
    case (everything eventually gets checked off) gets its own message
    rather than a broken-looking blank grid."""
    week_plan_id = make_week_plan()
    conn = database.get_connection()
    check_item(conn, week_plan_id, "milk", "ml")
    check_item(conn, week_plan_id, "flour", "g")
    conn.close()

    at = _load()
    at = _enter_shopping_mode(at)
    assert not at.exception
    assert not any(d.key == "grocery_table_editor_shopping" for d in at.dataframe)
    assert any("checked off" in s.value.lower() for s in at.success)
    assert any(e.label == "Checked off (2)" for e in at.expander)
