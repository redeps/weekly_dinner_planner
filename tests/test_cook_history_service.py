"""
Milestone 7 tests: cook history service functions
(services/cook_history.py).
"""

import datetime as dt
import sqlite3

import pytest

import models
from models import CalendarDay
from services import cook_history as history_service
from services import plan_generation as plan_service
from services import recipes as recipe_service


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    models.create_recipes_table(connection)
    models.create_recipe_ingredients_table(connection)
    models.create_week_plans_table(connection)
    models.create_plan_days_table(connection)
    models.create_cook_history_table(connection)
    yield connection
    connection.close()


def default_calendar():
    return [
        CalendarDay(day_of_week=day, is_busy=False, dinner_ready_time=dt.time(18, 0))
        for day in models.DAYS_OF_WEEK
    ]


def make_week_plan(conn, recipe_count=3):
    for i in range(recipe_count):
        recipe_service.create_recipe(
            conn,
            name=f"Recipe {i}",
            cook_time_minutes=20,
            family_enjoyment=3,
            seasonality="all-season",
            servings=4,
        )
    return plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31), calendar=default_calendar()
    )


def count_history_rows(conn):
    return conn.execute("SELECT COUNT(*) FROM cook_history").fetchone()[0]


# --- has_been_cooked ---


def test_has_been_cooked_false_initially(conn):
    week_plan_id = make_week_plan(conn)
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    assert history_service.has_been_cooked(conn, monday.id) is False


def test_has_been_cooked_true_after_marking(conn):
    week_plan_id = make_week_plan(conn)
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    history_service.mark_day_cooked(conn, monday.id)
    assert history_service.has_been_cooked(conn, monday.id) is True


# --- mark_day_cooked ---


def test_mark_day_cooked_raises_for_missing_plan_day(conn):
    with pytest.raises(ValueError):
        history_service.mark_day_cooked(conn, 999)


def test_mark_day_cooked_raises_when_no_recipe_assigned(conn):
    week_plan_id = conn.execute(
        "INSERT INTO week_plans (week_start_date) VALUES (?)", ("2026-08-31",)
    ).lastrowid
    plan_day_id = conn.execute(
        """
        INSERT INTO plan_days (week_plan_id, day_of_week, date, is_busy, dinner_ready_time, recipe_id)
        VALUES (?, 'monday', '2026-08-31', 0, '18:00', NULL)
        """,
        (week_plan_id,),
    ).lastrowid
    conn.commit()
    with pytest.raises(ValueError):
        history_service.mark_day_cooked(conn, plan_day_id)


def test_mark_day_cooked_creates_a_row_with_expected_fields(conn):
    week_plan_id = make_week_plan(conn)
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    new_id = history_service.mark_day_cooked(conn, monday.id)
    assert new_id is not None
    row = conn.execute(
        "SELECT recipe_id, plan_day_id, cooked_on FROM cook_history WHERE id = ?", (new_id,)
    ).fetchone()
    assert row[0] == monday.recipe_id
    assert row[1] == monday.id
    assert row[2] == monday.date  # defaults to the plan day's own date


def test_mark_day_cooked_accepts_cooked_on_override(conn):
    week_plan_id = make_week_plan(conn)
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    override = dt.date(2026, 9, 5)
    new_id = history_service.mark_day_cooked(conn, monday.id, cooked_on=override)
    row = conn.execute("SELECT cooked_on FROM cook_history WHERE id = ?", (new_id,)).fetchone()
    assert row[0] == override.isoformat()


def test_mark_day_cooked_is_idempotent_per_plan_day(conn):
    week_plan_id = make_week_plan(conn)
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    first = history_service.mark_day_cooked(conn, monday.id)
    second = history_service.mark_day_cooked(conn, monday.id)
    assert first is not None
    assert second is None
    assert count_history_rows(conn) == 1


# --- finalize_plan ---


def test_finalize_plan_marks_every_day(conn):
    week_plan_id = make_week_plan(conn)
    new_ids = history_service.finalize_plan(conn, week_plan_id)
    assert len(new_ids) == 7
    assert count_history_rows(conn) == 7


def test_finalize_plan_skips_days_with_no_recipe(conn):
    week_plan_id = conn.execute(
        "INSERT INTO week_plans (week_start_date) VALUES (?)", ("2026-08-31",)
    ).lastrowid
    conn.execute(
        """
        INSERT INTO plan_days (week_plan_id, day_of_week, date, is_busy, dinner_ready_time, recipe_id)
        VALUES (?, 'monday', '2026-08-31', 0, '18:00', NULL)
        """,
        (week_plan_id,),
    )
    conn.commit()
    new_ids = history_service.finalize_plan(conn, week_plan_id)
    assert new_ids == []
    assert count_history_rows(conn) == 0


def test_finalize_plan_is_safe_to_call_twice(conn):
    week_plan_id = make_week_plan(conn)
    history_service.finalize_plan(conn, week_plan_id)
    second_run_ids = history_service.finalize_plan(conn, week_plan_id)
    assert second_run_ids == []
    assert count_history_rows(conn) == 7


def test_finalize_plan_does_not_duplicate_an_already_marked_day(conn):
    week_plan_id = make_week_plan(conn)
    monday = next(
        d for d in plan_service.list_plan_days(conn, week_plan_id) if d.day_of_week == "monday"
    )
    history_service.mark_day_cooked(conn, monday.id)
    history_service.finalize_plan(conn, week_plan_id)
    assert count_history_rows(conn) == 7  # not 8


# --- list_recent_cook_history ---


def test_list_recent_cook_history_empty_when_nothing_cooked(conn):
    assert history_service.list_recent_cook_history(conn) == []


def test_list_recent_cook_history_orders_most_recent_first(conn):
    recipe_a = recipe_service.get_recipe(
        conn,
        recipe_service.create_recipe(
            conn, name="A", cook_time_minutes=10, family_enjoyment=3,
            seasonality="all-season", servings=2,
        ),
    )
    recipe_b = recipe_service.get_recipe(
        conn,
        recipe_service.create_recipe(
            conn, name="B", cook_time_minutes=10, family_enjoyment=3,
            seasonality="all-season", servings=2,
        ),
    )
    conn.execute(
        "INSERT INTO cook_history (recipe_id, cooked_on) VALUES (?, ?)",
        (recipe_a.id, "2026-08-01"),
    )
    conn.execute(
        "INSERT INTO cook_history (recipe_id, cooked_on) VALUES (?, ?)",
        (recipe_b.id, "2026-08-20"),
    )
    conn.commit()

    entries = history_service.list_recent_cook_history(conn)
    assert [e.recipe_name for e in entries] == ["B", "A"]


def test_list_recent_cook_history_respects_limit(conn):
    recipe = recipe_service.get_recipe(
        conn,
        recipe_service.create_recipe(
            conn, name="A", cook_time_minutes=10, family_enjoyment=3,
            seasonality="all-season", servings=2,
        ),
    )
    for day in range(1, 6):
        conn.execute(
            "INSERT INTO cook_history (recipe_id, cooked_on) VALUES (?, ?)",
            (recipe.id, f"2026-08-{day:02d}"),
        )
    conn.commit()

    assert len(history_service.list_recent_cook_history(conn, limit=2)) == 2
