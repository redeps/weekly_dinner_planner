"""
Milestone 14 tests: the Weekly Calendar Input screen's household-size UI --
the week-level yes/no gate and per-day override widgets it reveals (see
docs/PRODUCT_SPEC.md section 7). Uses streamlit.testing.v1 AppTest to drive
the real page script, same isolated-schema pattern as
tests/test_cook_history_ui.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database

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


def _load(isolated_db) -> AppTest:
    at = AppTest.from_file(WEEKLY_CALENDAR_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


def test_defaults_to_no_extra_days_with_no_override_widgets_shown(isolated_db):
    at = _load(isolated_db)
    assert not at.exception
    assert at.radio(key="hosting_extra_this_week").value == "No"
    assert len(at.multiselect) == 0
    assert not any(day.household_size_override is not None for day in at.session_state["weekly_calendar"])


def test_selecting_yes_reveals_day_multiselect(isolated_db):
    at = _load(isolated_db)
    at.radio(key="hosting_extra_this_week").set_value("Yes").run()
    assert len(at.multiselect(key="household_override_days").options) == 7


def test_selecting_a_day_reveals_its_size_input_and_sets_override(isolated_db):
    at = _load(isolated_db)
    at.radio(key="hosting_extra_this_week").set_value("Yes").run()
    at.multiselect(key="household_override_days").set_value(["wednesday"]).run()

    size_keys = [w.key for w in at.number_input if w.key.startswith("cal_household_size_")]
    assert size_keys == ["cal_household_size_wednesday"]
    at.number_input(key="cal_household_size_wednesday").set_value(8).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["wednesday"].household_size_override == 8
    assert days_by_name["monday"].household_size_override is None


def test_deselecting_a_day_clears_its_override(isolated_db):
    at = _load(isolated_db)
    at.radio(key="hosting_extra_this_week").set_value("Yes").run()
    at.multiselect(key="household_override_days").set_value(["wednesday"]).run()
    at.number_input(key="cal_household_size_wednesday").set_value(8).run()

    at.multiselect(key="household_override_days").set_value([]).run()

    days_by_name = {d.day_of_week: d for d in at.session_state["weekly_calendar"]}
    assert days_by_name["wednesday"].household_size_override is None
    size_keys = [w.key for w in at.number_input if w.key.startswith("cal_household_size_")]
    assert size_keys == []  # no per-day size widgets left


def test_switching_back_to_no_clears_all_overrides(isolated_db):
    at = _load(isolated_db)
    at.radio(key="hosting_extra_this_week").set_value("Yes").run()
    at.multiselect(key="household_override_days").set_value(["wednesday"]).run()
    at.number_input(key="cal_household_size_wednesday").set_value(8).run()

    at.radio(key="hosting_extra_this_week").set_value("No").run()

    assert not any(day.household_size_override is not None for day in at.session_state["weekly_calendar"])


def test_changing_default_household_size_persists_via_settings_service(isolated_db):
    from services.settings import get_default_household_size

    at = _load(isolated_db)
    at.number_input(key="default_household_size_input").set_value(6).run()

    conn = database.get_connection()
    assert get_default_household_size(conn) == 6
    conn.close()


# --- Regression: override survives navigating away and back ---
# (docs/DECISIONS.md -- the yes/no gate's radio had no computed `index=`,
# so a fresh widget instance after navigation defaulted to "No" and the
# page's own end-of-script rebuild then overwrote the still-correct
# override with None. Uses real st.switch_page() navigation, not a
# hand-copied session_state dict, since the latter doesn't reproduce
# Streamlit's actual widget-state lifecycle across pages -- confirmed
# during investigation that a naive copy made the bug look already-fixed
# when it wasn't.)


def test_household_override_survives_navigating_away_and_back(isolated_db):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    at.radio(key="hosting_extra_this_week").set_value("Yes")
    at = at.run()
    at.multiselect(key="household_override_days").set_value(["wednesday"])
    at = at.run()
    at.number_input(key="cal_household_size_wednesday").set_value(9)
    at = at.run()

    at = at.switch_page("pages/5_Week_Plan.py").run()
    at = at.switch_page("pages/4_Weekly_Calendar.py").run()

    assert not at.exception
    wed = next(d for d in at.session_state["weekly_calendar"] if d.day_of_week == "wednesday")
    assert wed.household_size_override == 9
    assert at.radio(key="hosting_extra_this_week").value == "Yes"
    assert at.multiselect(key="household_override_days").value == ["wednesday"]
