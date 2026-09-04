"""
Milestone 17 tests: manual grocery item service functions
(services/grocery_items.py) — the leading-number parser, and
add/remove/list CRUD for one-off vs. recurring items.

Uses an isolated per-test Postgres schema — never touches the `public`
schema. See docs/DECISIONS.md — Milestone 13 hosting architecture.
"""

import pytest

import database
from services import grocery_items as grocery_items_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def make_week_plan(conn, week_start="2026-08-31"):
    week_plan_id = conn.execute(
        "INSERT INTO week_plans (week_start_date) VALUES (%s) RETURNING id", (week_start,)
    ).fetchone()[0]
    conn.commit()
    return week_plan_id


# --- parse_leading_quantity: the leading-number regex, the fix for the
# real data-loss bug found during investigation (a whole pasted line
# stored as `name` with no separate quantity would otherwise lose a
# leading number to canonicalize_ingredient_name()'s own noise-stripping) ---


@pytest.mark.parametrize(
    "line,expected_quantity,expected_name",
    [
        ("6 eggs", 6.0, "eggs"),  # the motivating case
        ("2 rolls of paper towels", 2.0, "rolls of paper towels"),
        ("2.5 lbs ground beef", 2.5, "lbs ground beef"),
        ("  10   apples", 10.0, "apples"),  # extra whitespace tolerated
        ("Paper towels", None, "Paper towels"),  # no leading number at all
        ("24oz peanut butter", None, "24oz peanut butter"),  # no space after the digits -- not a count
        ("", None, ""),
        ("   ", None, ""),
        ("Dish soap 2 bottles", None, "Dish soap 2 bottles"),  # number isn't *leading*
    ],
)
def test_parse_leading_quantity(line, expected_quantity, expected_name):
    quantity, name = grocery_items_service.parse_leading_quantity(line)
    assert quantity == expected_quantity
    assert name == expected_name


def test_parse_leading_quantity_never_raises_on_garbage_input():
    assert grocery_items_service.parse_leading_quantity("!!! ??? ***") == (None, "!!! ??? ***")


# --- add_item / remove_item ---


def test_add_item_returns_id_and_persists(conn):
    item_id = grocery_items_service.add_item(
        conn, week_plan_id=None, name="Paper towels", quantity=2.0, store_category="other"
    )
    assert isinstance(item_id, int)
    items = grocery_items_service.list_manual_items(conn)
    assert [i.name for i in items] == ["Paper towels"]
    assert items[0].quantity == 2.0
    assert items[0].week_plan_id is None


def test_add_item_rejects_invalid_store_category(conn):
    with pytest.raises(ValueError):
        grocery_items_service.add_item(conn, week_plan_id=None, name="X", store_category="nope")


def test_remove_item_deletes_it(conn):
    item_id = grocery_items_service.add_item(conn, week_plan_id=None, name="Paper towels")
    grocery_items_service.remove_item(conn, item_id)
    assert grocery_items_service.list_manual_items(conn) == []


def test_remove_item_is_a_noop_when_not_found(conn):
    grocery_items_service.remove_item(conn, 999999)  # must not raise


# --- one-off items: scoped to a single week_plan_id ---


def test_one_off_item_appears_only_for_its_own_week(conn):
    week_a = make_week_plan(conn, "2026-08-31")
    week_b = make_week_plan(conn, "2026-09-07")
    grocery_items_service.add_item(conn, week_plan_id=week_a, name="Birthday candles")

    items_for_a = grocery_items_service.list_manual_items(conn, week_a)
    items_for_b = grocery_items_service.list_manual_items(conn, week_b)

    assert [i.name for i in items_for_a] == ["Birthday candles"]
    assert items_for_b == []


def test_one_off_item_does_not_appear_in_recurring_only_listing(conn):
    week_a = make_week_plan(conn)
    grocery_items_service.add_item(conn, week_plan_id=week_a, name="Birthday candles")
    assert grocery_items_service.list_manual_items(conn) == []  # recurring-only view


# --- recurring items: appear across every week_plan_id ---


def test_recurring_item_appears_across_multiple_different_week_plan_ids(conn):
    week_a = make_week_plan(conn, "2026-08-31")
    week_b = make_week_plan(conn, "2026-09-07")
    grocery_items_service.add_item(conn, week_plan_id=None, name="Milk")

    assert [i.name for i in grocery_items_service.list_manual_items(conn, week_a)] == ["Milk"]
    assert [i.name for i in grocery_items_service.list_manual_items(conn, week_b)] == ["Milk"]
    assert [i.name for i in grocery_items_service.list_manual_items(conn)] == ["Milk"]  # management view too


def test_recurring_and_one_off_items_both_appear_for_the_relevant_week(conn):
    week_a = make_week_plan(conn)
    grocery_items_service.add_item(conn, week_plan_id=None, name="Milk")
    grocery_items_service.add_item(conn, week_plan_id=week_a, name="Birthday candles")

    names = {i.name for i in grocery_items_service.list_manual_items(conn, week_a)}
    assert names == {"Milk", "Birthday candles"}


def test_list_manual_items_ordered_by_entry_order(conn):
    grocery_items_service.add_item(conn, week_plan_id=None, name="Second added")
    grocery_items_service.add_item(conn, week_plan_id=None, name="First added")
    # entry order, not alphabetical -- matches list_ingredients()'s own ORDER BY id
    names = [i.name for i in grocery_items_service.list_manual_items(conn)]
    assert names == ["Second added", "First added"]
