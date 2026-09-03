"""
Weekly Calendar screen's special-occasion direct-assignment section (see
docs/DECISIONS.md) -- a third week-gated section (yes/no -> multiselect of
days -> per-day recipe picker) mirroring the household-size override's
shape, restricted to is_special_occasion recipes, hidden entirely when
none exist. Uses streamlit.testing.v1 AppTest, same isolated-schema
pattern as tests/test_household_scaling_ui.py.
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


def make_special_occasion_recipe(name="Holiday Roast"):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name=name,
        cook_time_minutes=120,
        family_enjoyment=5,
        seasonality="all-season",
        servings=8,
        is_special_occasion=True,
    )
    conn.close()
    return recipe_id


def _load(isolated_db) -> AppTest:
    at = AppTest.from_file(WEEKLY_CALENDAR_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


# --- empty state ---


def test_section_hidden_when_no_special_occasion_recipes_exist(isolated_db):
    at = _load(isolated_db)
    assert not at.exception
    assert not any("Special-occasion recipes" in s.value for s in at.subheader)
    assert not any(w.key == "special_occasion_this_week" for w in at.radio)


def test_section_shown_when_a_special_occasion_recipe_exists(isolated_db):
    make_special_occasion_recipe()
    at = _load(isolated_db)
    assert not at.exception
    assert any("Special-occasion recipes" in s.value for s in at.subheader)
    assert any(w.key == "special_occasion_this_week" for w in at.radio)


# --- assignment flow ---


def test_defaults_to_no_extra_days_with_no_picker_shown(isolated_db):
    make_special_occasion_recipe()
    at = _load(isolated_db)
    assert at.radio(key="special_occasion_this_week").value == "No"
    assert not any(w.key.startswith("cal_special_occasion_") for w in at.selectbox)
    assert not any(day.assigned_recipe_id is not None for day in at.session_state["weekly_calendar"])


def test_selecting_yes_reveals_day_multiselect(isolated_db):
    make_special_occasion_recipe()
    at = _load(isolated_db)
    at.radio(key="special_occasion_this_week").set_value("Yes").run()
    assert len(at.multiselect(key="special_occasion_days").options) == 7


def test_selecting_a_day_reveals_placeholder_picker_with_no_assignment_yet(isolated_db):
    make_special_occasion_recipe()
    at = _load(isolated_db)
    at.radio(key="special_occasion_this_week").set_value("Yes").run()
    at.multiselect(key="special_occasion_days").set_value(["thursday"]).run()

    picker_keys = [w.key for w in at.selectbox if w.key.startswith("cal_special_occasion_")]
    assert picker_keys == ["cal_special_occasion_thursday"]
    assert at.selectbox(key="cal_special_occasion_thursday").value is None
    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["thursday"].assigned_recipe_id is None


def test_choosing_a_recipe_sets_the_assignment(isolated_db):
    recipe_id = make_special_occasion_recipe(name="Holiday Roast")
    at = _load(isolated_db)
    at.radio(key="special_occasion_this_week").set_value("Yes").run()
    at.multiselect(key="special_occasion_days").set_value(["thursday"]).run()
    at.selectbox(key="cal_special_occasion_thursday").set_value(recipe_id).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["thursday"].assigned_recipe_id == recipe_id
    assert days_by_name["monday"].assigned_recipe_id is None


def test_deselecting_a_day_clears_its_assignment(isolated_db):
    recipe_id = make_special_occasion_recipe()
    at = _load(isolated_db)
    at.radio(key="special_occasion_this_week").set_value("Yes").run()
    at.multiselect(key="special_occasion_days").set_value(["thursday"]).run()
    at.selectbox(key="cal_special_occasion_thursday").set_value(recipe_id).run()

    at.multiselect(key="special_occasion_days").set_value([]).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["thursday"].assigned_recipe_id is None
    picker_keys = [w.key for w in at.selectbox if w.key.startswith("cal_special_occasion_")]
    assert picker_keys == []


def test_switching_back_to_no_clears_all_assignments(isolated_db):
    recipe_id = make_special_occasion_recipe()
    at = _load(isolated_db)
    at.radio(key="special_occasion_this_week").set_value("Yes").run()
    at.multiselect(key="special_occasion_days").set_value(["thursday"]).run()
    at.selectbox(key="cal_special_occasion_thursday").set_value(recipe_id).run()

    at.radio(key="special_occasion_this_week").set_value("No").run()

    assert not any(day.assigned_recipe_id is not None for day in at.session_state["weekly_calendar"])


# --- Regression: assignment survives navigating away and back (same root
# cause and fix as the household-size override -- see
# tests/test_household_scaling_ui.py and docs/DECISIONS.md) ---


def test_assignment_survives_navigating_away_and_back(isolated_db):
    recipe_id = make_special_occasion_recipe(name="Holiday Roast")

    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    at.radio(key="special_occasion_this_week").set_value("Yes")
    at = at.run()
    at.multiselect(key="special_occasion_days").set_value(["thursday"])
    at = at.run()
    at.selectbox(key="cal_special_occasion_thursday").set_value(recipe_id)
    at = at.run()

    at = at.switch_page("pages/5_Week_Plan.py").run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    assert not at.exception
    thu = next(d for d in at.session_state["weekly_calendar"] if d.day_of_week == "thursday")
    assert thu.assigned_recipe_id == recipe_id
    assert at.radio(key="special_occasion_this_week").value == "Yes"
    assert at.multiselect(key="special_occasion_days").value == ["thursday"]
    assert at.selectbox(key="cal_special_occasion_thursday").value == recipe_id
