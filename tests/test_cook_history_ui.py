"""
Milestone 8: verifies, against the actual Week Plan page, that
re-rendering never creates duplicate cook_history rows — the specific
failure mode docs/AGENT_INSTRUCTIONS.md §4 warns about (Streamlit reruns
the whole script on every interaction, so a history write in rendering
code could turn one user action into duplicate rows).

Uses streamlit.testing.v1.AppTest to drive the real page script, with
database.DATA_DIR/DB_PATH monkeypatched to an isolated temp file so this
never touches the real data/ directory.
"""

import datetime as dt
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.calendar import build_default_week_calendar
from services.plan_generation import generate_week_plan
from services.recipes import create_recipe

REPO = Path(__file__).parent.parent
WEEK_PLAN_PAGE = str(REPO / "pages" / "5_Week_Plan.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")


@pytest.fixture
def week_plan_id(isolated_db):
    conn = database.get_connection()
    create_recipe(
        conn,
        name="Test Recipe",
        cook_time_minutes=20,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    week_plan_id = generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=build_default_week_calendar()
    )
    conn.close()
    return week_plan_id


def count_cook_history_rows() -> int:
    conn = database.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM cook_history").fetchone()[0]
    conn.close()
    return count


def test_loading_the_page_does_not_write_history(week_plan_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE).run()
    assert not at.exception
    assert count_cook_history_rows() == 0


def test_rerendering_without_clicking_does_not_write_history(week_plan_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE).run()
    for _ in range(5):
        at = at.run()
        assert not at.exception
    assert count_cook_history_rows() == 0


def test_one_mark_cooked_click_writes_exactly_one_row(week_plan_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE).run()
    mark_buttons = [b for b in at.button if b.key and b.key.startswith("mark_cooked_")]
    assert len(mark_buttons) == 7

    at = mark_buttons[0].click().run()
    assert not at.exception
    assert count_cook_history_rows() == 1


def test_rerendering_after_a_click_does_not_duplicate_the_row(week_plan_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE).run()
    mark_buttons = [b for b in at.button if b.key and b.key.startswith("mark_cooked_")]
    at = mark_buttons[0].click().run()
    assert count_cook_history_rows() == 1

    # Simulate further reruns from unrelated interactions (Streamlit reruns
    # the whole script on every widget interaction) — must not re-trigger
    # the write for the day that's already marked.
    for _ in range(5):
        at = at.run()
        assert not at.exception
    assert count_cook_history_rows() == 1


def test_the_marked_day_shows_cooked_state_instead_of_a_button(week_plan_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE).run()
    mark_buttons = [b for b in at.button if b.key and b.key.startswith("mark_cooked_")]
    marked_key = mark_buttons[0].key

    at = mark_buttons[0].click().run()

    remaining_mark_buttons = [b for b in at.button if b.key == marked_key]
    assert remaining_mark_buttons == [], "the button should disappear once marked cooked"
    assert any("Cooked" in m.value for m in at.markdown)


def test_finalize_plan_click_writes_seven_rows_and_is_safe_to_repeat(week_plan_id):
    at = AppTest.from_file(WEEK_PLAN_PAGE).run()
    finalize_btn = [b for b in at.button if b.label == "Finalize Plan (mark all cooked)"][0]

    at = finalize_btn.click().run()
    assert not at.exception
    assert count_cook_history_rows() == 7

    # Clicking it again (or re-rendering) must not duplicate anything.
    finalize_btn2 = [b for b in at.button if b.label == "Finalize Plan (mark all cooked)"][0]
    at = finalize_btn2.click().run()
    assert count_cook_history_rows() == 7
