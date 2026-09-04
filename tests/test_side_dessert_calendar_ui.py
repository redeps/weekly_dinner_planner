"""
Milestone 16 Phase 2: the Weekly Calendar screen's Side dishes and
Dessert sections -- two week-gated (yes/no -> multiselect of days ->
per-day multiselect of recipes) sections sharing one helper
(`_render_dish_attachment_section` in pages/4_Weekly_Calendar.py), mirroring
the household-size override's and special-occasion assignment's shape.
Uses streamlit.testing.v1 AppTest, same isolated-schema pattern as
tests/test_household_scaling_ui.py and tests/test_special_occasion_calendar_ui.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.recipes import create_recipe

REPO = Path(__file__).parent.parent
HOME_PAGE = str(REPO / "app.py")
WEEKLY_CALENDAR_PAGE = str(REPO / "pages" / "4_Weekly_Calendar.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def make_recipe(name, course):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name=name,
        cook_time_minutes=15,
        family_enjoyment=4,
        seasonality="all-season",
        servings=4,
        course=course,
    )
    conn.close()
    return recipe_id


def _load(isolated_db) -> AppTest:
    at = AppTest.from_file(WEEKLY_CALENDAR_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


# --- empty state: hidden entirely when no recipe of that course exists ---


def test_side_section_hidden_when_no_side_recipes_exist(isolated_db):
    at = _load(isolated_db)
    assert not at.exception
    assert not any("Side dishes" in s.value for s in at.subheader)
    assert not any(w.key == "side_dish_this_week" for w in at.radio)


def test_dessert_section_hidden_when_no_dessert_recipes_exist(isolated_db):
    at = _load(isolated_db)
    assert not at.exception
    assert not any("Desserts" in s.value for s in at.subheader)
    assert not any(w.key == "dessert_this_week" for w in at.radio)


def test_side_section_shown_when_a_side_recipe_exists(isolated_db):
    make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    assert not at.exception
    assert any("Side dishes" in s.value for s in at.subheader)
    assert any(w.key == "side_dish_this_week" for w in at.radio)


def test_dessert_section_shown_when_a_dessert_recipe_exists(isolated_db):
    make_recipe("Apple Crumble", "dessert")
    at = _load(isolated_db)
    assert not at.exception
    assert any("Desserts" in s.value for s in at.subheader)
    assert any(w.key == "dessert_this_week" for w in at.radio)


# --- assignment flow (side dishes; dessert shares the same helper) ---


def test_defaults_to_no_extra_days_with_no_picker_shown(isolated_db):
    make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    assert at.radio(key="side_dish_this_week").value == "No"
    assert not any(w.key.startswith("side_dish_") and w.key != "side_dish_this_week" for w in at.multiselect)
    assert not any(day.side_recipe_ids for day in at.session_state["weekly_calendar"])


def test_selecting_yes_reveals_day_multiselect(isolated_db):
    make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    at.radio(key="side_dish_this_week").set_value("Yes").run()
    assert len(at.multiselect(key="side_dish_days").options) == 7


def test_selecting_a_day_reveals_recipe_multiselect_with_no_attachment_yet(isolated_db):
    make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["thursday"]).run()

    picker_keys = [w.key for w in at.multiselect if w.key.startswith("side_dish_thursday")]
    assert picker_keys == ["side_dish_thursday"]
    assert at.multiselect(key="side_dish_thursday").value == []
    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["thursday"].side_recipe_ids == []


def test_choosing_multiple_dishes_attaches_all_of_them(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")
    pudding_id = make_recipe("Yorkshire Pudding", "side")
    at = _load(isolated_db)
    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["thursday"]).run()
    at.multiselect(key="side_dish_thursday").set_value([salad_id, pudding_id]).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert set(days_by_name["thursday"].side_recipe_ids) == {salad_id, pudding_id}
    assert days_by_name["monday"].side_recipe_ids == []


def test_deselecting_a_day_clears_its_attachments(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["thursday"]).run()
    at.multiselect(key="side_dish_thursday").set_value([salad_id]).run()

    at.multiselect(key="side_dish_days").set_value([]).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["thursday"].side_recipe_ids == []
    picker_keys = [w.key for w in at.multiselect if w.key.startswith("side_dish_thursday")]
    assert picker_keys == []


def test_switching_back_to_no_clears_all_attachments(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["thursday"]).run()
    at.multiselect(key="side_dish_thursday").set_value([salad_id]).run()

    at.radio(key="side_dish_this_week").set_value("No").run()

    assert not any(day.side_recipe_ids for day in at.session_state["weekly_calendar"])


# --- sides and desserts on the same day are independent of each other ---


def test_a_day_can_have_a_side_and_a_dessert_at_once(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")
    crumble_id = make_recipe("Apple Crumble", "dessert")
    at = _load(isolated_db)

    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["sunday"]).run()
    at.multiselect(key="side_dish_sunday").set_value([salad_id]).run()

    at.radio(key="dessert_this_week").set_value("Yes").run()
    at.multiselect(key="dessert_days").set_value(["sunday"]).run()
    at.multiselect(key="dessert_sunday").set_value([crumble_id]).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["sunday"].side_recipe_ids == [salad_id]
    assert days_by_name["sunday"].dessert_recipe_ids == [crumble_id]


# --- Regression: household-size override and dish attachments don't
# clobber each other -- the exact bug class already found once for the
# household-size override's own gate (see docs/DECISIONS.md) ---


def test_editing_household_override_does_not_clear_existing_dish_attachment(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["wednesday"]).run()
    at.multiselect(key="side_dish_wednesday").set_value([salad_id]).run()

    at.radio(key="hosting_extra_this_week").set_value("Yes").run()
    at.multiselect(key="household_override_days").set_value(["wednesday"]).run()
    at.number_input(key="cal_household_size_wednesday").set_value(8).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["wednesday"].household_size_override == 8
    assert days_by_name["wednesday"].side_recipe_ids == [salad_id]


def test_removing_household_override_does_not_clear_dish_attachment(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")
    at = _load(isolated_db)
    at.radio(key="hosting_extra_this_week").set_value("Yes").run()
    at.multiselect(key="household_override_days").set_value(["wednesday"]).run()
    at.number_input(key="cal_household_size_wednesday").set_value(8).run()

    at.radio(key="side_dish_this_week").set_value("Yes").run()
    at.multiselect(key="side_dish_days").set_value(["wednesday"]).run()
    at.multiselect(key="side_dish_wednesday").set_value([salad_id]).run()

    at.multiselect(key="household_override_days").set_value([]).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["wednesday"].household_size_override is None
    assert days_by_name["wednesday"].side_recipe_ids == [salad_id]


# --- Regression: attachments survive navigating away and back (same root
# cause/fix class as household-size override and special-occasion
# assignment -- see tests/test_household_scaling_ui.py and docs/DECISIONS.md) ---


def test_attachment_survives_navigating_away_and_back(isolated_db):
    salad_id = make_recipe("Garden Salad", "side")

    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    at.radio(key="side_dish_this_week").set_value("Yes")
    at = at.run()
    at.multiselect(key="side_dish_days").set_value(["thursday"])
    at = at.run()
    at.multiselect(key="side_dish_thursday").set_value([salad_id])
    at = at.run()

    at = at.switch_page("pages/5_Week_Plan.py").run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    assert not at.exception
    thu = next(d for d in at.session_state["weekly_calendar"] if d.day_of_week == "thursday")
    assert thu.side_recipe_ids == [salad_id]
    assert at.radio(key="side_dish_this_week").value == "Yes"
    assert at.multiselect(key="side_dish_days").value == ["thursday"]
    assert at.multiselect(key="side_dish_thursday").value == [salad_id]
