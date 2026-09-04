"""
Milestone 16 Phase 2: Week Plan's read-only display of a day's attached
sides/desserts below its main recipe (pages/5_Week_Plan.py). See
docs/DECISIONS.md. Uses streamlit.testing.v1 AppTest, same isolated-schema
pattern as tests/test_cook_history_ui.py.
"""

import datetime as dt
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from models import CalendarDay, DAYS_OF_WEEK
from services.plan_generation import generate_week_plan
from services.recipes import create_recipe

REPO = Path(__file__).parent.parent
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


def make_recipe(conn, name, course="main"):
    return create_recipe(
        conn,
        name=name,
        cook_time_minutes=15,
        family_enjoyment=4,
        seasonality="all-season",
        servings=4,
        course=course,
    )


def calendar_with_attachments(day_name, *, side_ids=(), dessert_ids=()):
    return [
        CalendarDay(
            day_of_week=day,
            is_busy=False,
            dinner_ready_time=dt.time(18, 0),
            side_recipe_ids=list(side_ids) if day == day_name else [],
            dessert_recipe_ids=list(dessert_ids) if day == day_name else [],
        )
        for day in DAYS_OF_WEEK
    ]


def _load() -> AppTest:
    at = AppTest.from_file(WEEK_PLAN_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


def test_day_with_no_attachments_shows_no_dish_caption(isolated_db):
    conn = database.get_connection()
    make_recipe(conn, "Roast Chicken")
    generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31),
        calendar=calendar_with_attachments("monday"),
    )
    conn.close()

    at = _load()
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert not any("Side:" in c or "Dessert:" in c for c in captions)


def test_day_with_a_side_shows_it_below_the_main(isolated_db):
    conn = database.get_connection()
    make_recipe(conn, "Roast Chicken")
    salad_id = make_recipe(conn, "Garden Salad", course="side")
    generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31),
        calendar=calendar_with_attachments("monday", side_ids=[salad_id]),
    )
    conn.close()

    at = _load()
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any(c == "Side: Garden Salad" for c in captions), captions


def test_day_with_multiple_sides_and_a_dessert_shows_all_of_them(isolated_db):
    conn = database.get_connection()
    make_recipe(conn, "Roast Chicken")
    salad_id = make_recipe(conn, "Garden Salad", course="side")
    pudding_id = make_recipe(conn, "Yorkshire Pudding", course="side")
    crumble_id = make_recipe(conn, "Apple Crumble", course="dessert")
    generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31),
        calendar=calendar_with_attachments(
            "sunday", side_ids=[salad_id, pudding_id], dessert_ids=[crumble_id]
        ),
    )
    conn.close()

    at = _load()
    assert not at.exception
    captions = [c.value for c in at.caption]
    dish_caption = next(c for c in captions if c.startswith("Side:") or c.startswith("Dessert:"))
    assert "Side: Garden Salad" in dish_caption
    assert "Side: Yorkshire Pudding" in dish_caption
    assert "Dessert: Apple Crumble" in dish_caption


def test_no_detach_action_offered_on_week_plan(isolated_db):
    """Read-only for this phase -- Weekly Calendar remains the only place
    attachments are made or removed (see docs/DECISIONS.md)."""
    conn = database.get_connection()
    make_recipe(conn, "Roast Chicken")
    salad_id = make_recipe(conn, "Garden Salad", course="side")
    generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31),
        calendar=calendar_with_attachments("monday", side_ids=[salad_id]),
    )
    conn.close()

    at = _load()
    assert not at.exception
    assert not any("detach" in b.label.lower() or "remove" in b.label.lower() for b in at.button)
