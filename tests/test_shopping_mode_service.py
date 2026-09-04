"""
Milestone 18 Phase 1 tests: shopping mode's completion flag
(services/shopping_mode.py, week_plans.shopping_completed_at).

Uses an isolated per-test Postgres schema — never touches the `public`
schema. See docs/DECISIONS.md — Milestone 13 hosting architecture.
"""

import datetime as dt
import random

import pytest

import database
from services import plan_generation as plan_service
from services import shopping_mode as shopping_service
from services.calendar import build_default_week_calendar
from services.recipes import create_recipe


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def make_week_plan(conn, week_start):
    create_recipe(
        conn,
        name=f"Recipe {week_start}",
        cook_time_minutes=20,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    return plan_service.generate_week_plan(
        conn, week_start_date=dt.date.fromisoformat(week_start),
        calendar=build_default_week_calendar(), rng=random.Random(0),
    )


def test_new_week_plan_starts_with_shopping_completed_at_unset(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    week_plan = plan_service.get_week_plan(conn, week_plan_id)
    assert week_plan.shopping_completed_at is None


def test_mark_shopping_completed_sets_the_timestamp(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.mark_shopping_completed(conn, week_plan_id)
    week_plan = plan_service.get_week_plan(conn, week_plan_id)
    assert week_plan.shopping_completed_at is not None


def test_mark_shopping_completed_only_affects_the_given_week_plan(conn):
    week_a = make_week_plan(conn, "2026-08-31")
    week_b = make_week_plan(conn, "2026-09-07")
    shopping_service.mark_shopping_completed(conn, week_a)

    assert plan_service.get_week_plan(conn, week_a).shopping_completed_at is not None
    assert plan_service.get_week_plan(conn, week_b).shopping_completed_at is None


def test_new_week_plan_starts_unset_even_after_a_prior_week_was_completed(conn):
    """A fresh generate_week_plan() call must never inherit or be
    affected by a previous week's completion state -- confirming the
    'zero extra logic' claim directly rather than assuming it."""
    week_a = make_week_plan(conn, "2026-08-31")
    shopping_service.mark_shopping_completed(conn, week_a)
    assert plan_service.get_week_plan(conn, week_a).shopping_completed_at is not None

    week_b = make_week_plan(conn, "2026-09-07")
    assert plan_service.get_week_plan(conn, week_b).shopping_completed_at is None


def test_get_latest_week_plan_reflects_completion_state(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.mark_shopping_completed(conn, week_plan_id)
    latest = plan_service.get_latest_week_plan(conn)
    assert latest.id == week_plan_id
    assert latest.shopping_completed_at is not None
