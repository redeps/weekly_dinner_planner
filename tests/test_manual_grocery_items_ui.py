"""
Milestone 17: manual grocery items UI on pages/6_Grocery_List.py -- the
shared paste-in-and-review flow (one-off and recurring), and the
persistent add/remove lists. Uses streamlit.testing.v1 AppTest, same
isolated-schema pattern as tests/test_grocery_list_service.py's UI
siblings.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.grocery_items import add_item
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
    import datetime as dt

    from services.calendar import build_default_week_calendar

    conn = database.get_connection()
    create_recipe(
        conn,
        name="Roast Chicken",
        cook_time_minutes=60,
        family_enjoyment=4,
        seasonality="all-season",
        servings=4,
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


# --- end-to-end: paste -> parse -> review -> confirm (one-off) ---


def test_paste_parse_review_confirm_adds_one_off_items(week_plan_id):
    at = _load(week_plan_id)
    at.text_area(key="one_off_paste_input").set_value("6 eggs\nDish soap")
    at = at.run()

    at = [b for b in at.button if b.key == "one_off_parse"][0].click().run()
    assert not at.exception

    # Review step: two editable rows, pre-filled from parsing.
    assert at.text_input(key="one_off_name_1").value == "eggs"
    assert at.text_input(key="one_off_qty_1").value == "6"
    assert at.text_input(key="one_off_name_2").value == "Dish soap"
    assert at.text_input(key="one_off_qty_2").value == ""

    at = [b for b in at.button if b.key == "one_off_confirm"][0].click().run()
    assert not at.exception

    from services.grocery_items import list_manual_items

    conn = database.get_connection()
    items = {i.name: i for i in list_manual_items(conn, week_plan_id)}
    conn.close()
    assert items["eggs"].quantity == 6.0
    assert items["eggs"].week_plan_id == week_plan_id
    assert items["Dish soap"].quantity is None


def test_confirmed_one_off_item_appears_on_the_grocery_list_table(week_plan_id):
    at = _load(week_plan_id)
    at.text_area(key="one_off_paste_input").set_value("Birthday candles")
    at = at.run()
    at = [b for b in at.button if b.key == "one_off_parse"][0].click().run()
    at = [b for b in at.button if b.key == "one_off_confirm"][0].click().run()

    assert not at.exception
    table_rows = at.dataframe[0].value.to_dict("records")
    assert any(row["Ingredient"] == "Birthday candles" for row in table_rows)


def test_review_row_can_be_edited_before_confirming(week_plan_id):
    at = _load(week_plan_id)
    at.text_area(key="one_off_paste_input").set_value("eggs")
    at = at.run()
    at = [b for b in at.button if b.key == "one_off_parse"][0].click().run()

    at.text_input(key="one_off_qty_1").set_value("12")
    at.text_input(key="one_off_unit_1").set_value("large")
    at = at.run()
    at = [b for b in at.button if b.key == "one_off_confirm"][0].click().run()

    from services.grocery_items import list_manual_items

    conn = database.get_connection()
    item = list_manual_items(conn, week_plan_id)[0]
    conn.close()
    assert item.quantity == 12.0
    assert item.unit == "large"


def test_removing_a_review_row_excludes_it_from_confirm(week_plan_id):
    at = _load(week_plan_id)
    at.text_area(key="one_off_paste_input").set_value("eggs\nmilk")
    at = at.run()
    at = [b for b in at.button if b.key == "one_off_parse"][0].click().run()

    at = [b for b in at.button if b.key == "one_off_remove_1"][0].click().run()
    assert not any(w.key == "one_off_name_1" for w in at.text_input)  # row 1 gone

    at = [b for b in at.button if b.key == "one_off_confirm"][0].click().run()

    from services.grocery_items import list_manual_items

    conn = database.get_connection()
    names = {i.name for i in list_manual_items(conn, week_plan_id)}
    conn.close()
    assert names == {"milk"}


def test_discard_clears_the_review_without_saving(week_plan_id):
    at = _load(week_plan_id)
    at.text_area(key="one_off_paste_input").set_value("eggs")
    at = at.run()
    at = [b for b in at.button if b.key == "one_off_parse"][0].click().run()

    at = [b for b in at.button if b.key == "one_off_discard"][0].click().run()
    assert not any(w.key == "one_off_name_1" for w in at.text_input)

    from services.grocery_items import list_manual_items

    conn = database.get_connection()
    assert list_manual_items(conn, week_plan_id) == []
    conn.close()


# --- recurring items: same mechanism, week_plan_id=None ---


def test_recurring_item_added_via_paste_in_appears_every_week(week_plan_id):
    at = _load(week_plan_id)
    at.text_area(key="recurring_paste_input").set_value("Dish soap")
    at = at.run()
    at = [b for b in at.button if b.key == "recurring_parse"][0].click().run()
    at = [b for b in at.button if b.key == "recurring_confirm"][0].click().run()
    assert not at.exception

    from services.grocery_items import list_manual_items

    conn = database.get_connection()
    recurring = list_manual_items(conn)  # recurring-only view
    conn.close()
    assert [i.name for i in recurring] == ["Dish soap"]
    assert recurring[0].week_plan_id is None


def test_recurring_items_management_list_shows_added_items_with_remove(isolated_db, week_plan_id):
    conn = database.get_connection()
    add_item(conn, week_plan_id=None, name="Dish soap")
    conn.close()

    at = _load(week_plan_id)
    assert not at.exception
    remove_buttons = [b for b in at.button if b.key.startswith("recurring_manage_remove_")]
    assert len(remove_buttons) == 1

    at = remove_buttons[0].click().run()

    from services.grocery_items import list_manual_items

    conn = database.get_connection()
    assert list_manual_items(conn) == []
    conn.close()


def test_recurring_list_shows_none_added_yet_when_empty(week_plan_id):
    at = _load(week_plan_id)
    assert not at.exception
    assert any("None added yet" in c.value for c in at.caption)


# --- one-off "added this week" management list ---


def test_one_off_items_management_list_shown_only_when_items_exist(isolated_db, week_plan_id):
    at = _load(week_plan_id)
    assert not any("Added this week" in c.value for c in at.caption)

    conn = database.get_connection()
    add_item(conn, week_plan_id=week_plan_id, name="Birthday candles")
    conn.close()

    at2 = _load(week_plan_id)
    assert any("Added this week" in c.value for c in at2.caption)
    remove_buttons = [b for b in at2.button if b.key.startswith("one_off_manage_remove_")]
    assert len(remove_buttons) == 1
