"""
Milestone 17 Phase 2 tests: persistent ingredient category overrides
(services/category_overrides.py).

Uses an isolated per-test Postgres schema — never touches the `public`
schema. See docs/DECISIONS.md — Milestone 13 hosting architecture.
"""

import pytest

import database
from services import category_overrides as override_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


# --- get_override / set_override ---


def test_get_override_returns_none_when_not_set(conn):
    assert override_service.get_override(conn, "milk") is None


def test_set_override_then_get_override_returns_it(conn):
    override_service.set_override(conn, "milk", "dairy")
    assert override_service.get_override(conn, "milk") == "dairy"


def test_set_override_upserts_rather_than_duplicating(conn):
    override_service.set_override(conn, "milk", "pantry")
    override_service.set_override(conn, "milk", "dairy")
    assert override_service.get_override(conn, "milk") == "dairy"
    count = conn.execute(
        "SELECT COUNT(*) FROM ingredient_category_overrides WHERE canonical_name = 'milk'"
    ).fetchone()[0]
    assert count == 1


def test_set_override_rejects_invalid_store_category(conn):
    with pytest.raises(ValueError):
        override_service.set_override(conn, "milk", "not-a-category")


def test_overrides_for_different_canonical_names_are_independent(conn):
    override_service.set_override(conn, "milk", "dairy")
    override_service.set_override(conn, "chorizo", "meat")
    assert override_service.get_override(conn, "milk") == "dairy"
    assert override_service.get_override(conn, "chorizo") == "meat"


# --- suggest_category_with_override ---


def test_suggest_category_with_override_falls_back_when_no_override_set(conn):
    # "chicken" is in categorization.py's static dictionary as "meat".
    assert override_service.suggest_category_with_override(conn, "chicken") == "meat"


def test_suggest_category_with_override_takes_precedence_over_static_dictionary(conn):
    # "chicken" would normally suggest "meat" -- an override must win.
    override_service.set_override(conn, "chicken", "frozen")
    assert override_service.suggest_category_with_override(conn, "chicken") == "frozen"


def test_suggest_category_with_override_applies_via_canonical_form(conn):
    """A correction made against one phrasing must apply to any other
    phrasing that canonicalizes to the same name -- confirming the
    override is keyed on the canonical form, not the raw string."""
    override_service.set_override(conn, "garlic", "produce")
    # "chopped" and "cloves" are both noise words stripped by
    # canonicalize_ingredient_name(), so both collapse to "garlic".
    assert override_service.suggest_category_with_override(conn, "garlic cloves") == "produce"
    assert override_service.suggest_category_with_override(conn, "chopped garlic") == "produce"


def test_suggest_category_with_override_returns_none_when_nothing_matches(conn):
    assert override_service.suggest_category_with_override(conn, "xyzzy-not-a-real-ingredient") is None


# --- detect_category_edits: the Grocery List page's diff-detection logic,
# tested directly with plain dicts since streamlit.testing.v1's Dataframe
# proxy has no way to simulate a live st.data_editor edit (confirmed
# directly, not assumed -- see docs/DECISIONS.md and
# tests/test_category_override_grocery_list_ui.py) ---


def test_detect_category_edits_finds_a_changed_row():
    original = [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    edited = [{"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    assert override_service.detect_category_edits(original, edited) == [("milk", "dairy")]


def test_detect_category_edits_ignores_unchanged_rows():
    original = [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    edited = [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    assert override_service.detect_category_edits(original, edited) == []


def test_detect_category_edits_ignores_non_category_changes():
    """Quantity/Unit are disabled columns in the real editor, but this
    pure function only cares about Category regardless."""
    original = [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    edited = [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "999", "Unit": "l"}]
    assert override_service.detect_category_edits(original, edited) == []


def test_detect_category_edits_finds_multiple_changed_rows():
    original = [
        {"Category": "Pantry", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"},
        {"Category": "Other", "Ingredient": "Chorizo", "Quantity": "1", "Unit": "each"},
    ]
    edited = [
        {"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"},
        {"Category": "Meat", "Ingredient": "Chorizo", "Quantity": "1", "Unit": "each"},
    ]
    assert override_service.detect_category_edits(original, edited) == [
        ("milk", "dairy"),
        ("chorizo", "meat"),
    ]


def test_detect_category_edits_derives_canonical_name_from_display_name():
    """The editor shows a title-cased canonical name ('Cornstarch'), not
    the raw stored ingredient text -- re-canonicalizing it must recover
    the same key build_grocery_list() itself groups by."""
    original = [{"Category": "Pantry", "Ingredient": "Cornstarch", "Quantity": "18", "Unit": "g"}]
    edited = [{"Category": "Other", "Ingredient": "Cornstarch", "Quantity": "18", "Unit": "g"}]
    assert override_service.detect_category_edits(original, edited) == [("cornstarch", "other")]


def test_detect_category_edits_end_to_end_via_set_override(conn):
    """The full loop: detect a change, then actually persist it via
    set_override, then confirm get_override reflects it."""
    original = [{"Category": "Pantry", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    edited = [{"Category": "Dairy", "Ingredient": "Milk", "Quantity": "200", "Unit": "ml"}]
    for canonical_name, new_category in override_service.detect_category_edits(original, edited):
        override_service.set_override(conn, canonical_name, new_category)
    assert override_service.get_override(conn, "milk") == "dairy"
