"""
Milestone 18 tests: shopping mode's completion flag (Phase 1,
week_plans.shopping_completed_at) and checked-off-item state (Phase 2,
grocery_checked_items) -- services/shopping_mode.py.

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


# --- Phase 2: check_item / uncheck_item / list_checked_items ---


def test_check_item_then_list_checked_items(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.check_item(conn, week_plan_id, "milk", "ml")
    assert shopping_service.list_checked_items(conn, week_plan_id) == [("milk", "ml")]


def test_check_item_is_a_noop_when_already_checked(conn):
    """UNIQUE(week_plan_id, canonical_name, unit) must not surface as a
    raised constraint violation -- checking an already-checked item is a
    clean no-op (ON CONFLICT DO NOTHING)."""
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.check_item(conn, week_plan_id, "milk", "ml")
    shopping_service.check_item(conn, week_plan_id, "milk", "ml")  # must not raise
    assert shopping_service.list_checked_items(conn, week_plan_id) == [("milk", "ml")]


def test_check_item_with_no_unit_does_not_create_duplicate_rows(conn):
    """The real motivating case for storing unit as '' rather than NULL:
    repeatedly checking a no-unit item must not silently insert
    duplicates (which a nullable-column UNIQUE constraint would allow,
    since Postgres never treats two NULLs as equal)."""
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.check_item(conn, week_plan_id, "birthday candles", "")
    shopping_service.check_item(conn, week_plan_id, "birthday candles", "")
    shopping_service.check_item(conn, week_plan_id, "birthday candles")  # default unit=""

    assert shopping_service.list_checked_items(conn, week_plan_id) == [("birthday candles", "")]
    count = conn.execute(
        "SELECT COUNT(*) FROM grocery_checked_items WHERE week_plan_id = %s", (week_plan_id,)
    ).fetchone()[0]
    assert count == 1


def test_uncheck_item_removes_it(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.check_item(conn, week_plan_id, "milk", "ml")
    shopping_service.uncheck_item(conn, week_plan_id, "milk", "ml")
    assert shopping_service.list_checked_items(conn, week_plan_id) == []


def test_uncheck_item_is_a_noop_when_not_checked(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.uncheck_item(conn, week_plan_id, "milk", "ml")  # must not raise
    assert shopping_service.list_checked_items(conn, week_plan_id) == []


def test_checked_items_are_independent_across_units_of_the_same_ingredient(conn):
    week_plan_id = make_week_plan(conn, "2026-08-31")
    shopping_service.check_item(conn, week_plan_id, "flour", "g")
    assert set(shopping_service.list_checked_items(conn, week_plan_id)) == {("flour", "g")}
    assert shopping_service.list_checked_items(conn, week_plan_id) != [("flour", "tbsp")]


def test_checked_items_are_scoped_to_their_own_week_plan(conn):
    week_a = make_week_plan(conn, "2026-08-31")
    week_b = make_week_plan(conn, "2026-09-07")
    shopping_service.check_item(conn, week_a, "milk", "ml")

    assert shopping_service.list_checked_items(conn, week_a) == [("milk", "ml")]
    assert shopping_service.list_checked_items(conn, week_b) == []


def test_a_completed_weeks_checked_items_do_not_leak_into_a_new_week(conn):
    week_a = make_week_plan(conn, "2026-08-31")
    shopping_service.check_item(conn, week_a, "milk", "ml")
    shopping_service.mark_shopping_completed(conn, week_a)

    week_b = make_week_plan(conn, "2026-09-07")
    assert shopping_service.list_checked_items(conn, week_b) == []
    # and the completed week's own checked items are still there, untouched
    assert shopping_service.list_checked_items(conn, week_a) == [("milk", "ml")]


# --- row_key / detect_checked_edits ---


def test_row_key_normalizes_the_no_value_placeholder_to_empty_string():
    from services.grocery_list import NO_VALUE_DISPLAY

    assert shopping_service.row_key("Milk", NO_VALUE_DISPLAY) == ("milk", "")
    assert shopping_service.row_key("Milk", "ml") == ("milk", "ml")


def test_detect_checked_edits_finds_a_newly_checked_row():
    original = [{"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml", "Checked": False}]
    edited = [{"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml", "Checked": True}]
    assert shopping_service.detect_checked_edits(original, edited) == [("milk", "ml")]


def test_detect_checked_edits_ignores_unchanged_rows():
    original = [{"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml", "Checked": False}]
    edited = [{"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml", "Checked": False}]
    assert shopping_service.detect_checked_edits(original, edited) == []


def test_detect_checked_edits_normalizes_no_unit_placeholder():
    from services.grocery_list import NO_VALUE_DISPLAY

    original = [
        {"Category": "Other", "Ingredient": "Birthday Candles", "Quantity": "—", "Unit": NO_VALUE_DISPLAY, "Checked": False}
    ]
    edited = [
        {"Category": "Other", "Ingredient": "Birthday Candles", "Quantity": "—", "Unit": NO_VALUE_DISPLAY, "Checked": True}
    ]
    assert shopping_service.detect_checked_edits(original, edited) == [("birthday candles", "")]


# --- Confirm export stays entirely unaffected by checked state ---


def test_build_grocery_list_output_unaffected_by_checked_state(conn):
    from services.grocery_list import build_grocery_list
    from services.ingredients import replace_recipe_ingredients

    recipe_id = create_recipe(
        conn, name="Pancakes", cook_time_minutes=10, family_enjoyment=3,
        seasonality="all-season", servings=4,
    )
    replace_recipe_ingredients(
        conn, recipe_id, [{"name": "milk", "quantity": 200, "unit": "ml", "store_category": "dairy"}]
    )
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 8, 31),
        calendar=build_default_week_calendar(), rng=random.Random(0),
    )

    before = build_grocery_list(conn, week_plan_id)
    assert before  # sanity check: there's real data to compare against

    shopping_service.check_item(conn, week_plan_id, "milk", "ml")
    after = build_grocery_list(conn, week_plan_id)

    assert before == after, "checking an item off must not change build_grocery_list()'s output"
