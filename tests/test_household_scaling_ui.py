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
