"""
Milestone 17 Phase 2: a persisted category override takes precedence
over the static categorization.py dictionary at Add/Edit Recipe's
import-time categorization call site
(services.category_overrides.suggest_category_with_override, wired in
place of services.categorization.suggest_category directly — see
docs/DECISIONS.md).

Drives the real page script via AppTest, mocking only the network-facing
recipe_import.parse_recipe_url() call (covered on its own in
tests/test_recipe_import_service.py) — categorization itself is real.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import database
from services import category_overrides, recipe_import

REPO = Path(__file__).parent.parent
HOME_PAGE = str(REPO / "app.py")
ADD_EDIT_PAGE = "pages/2_Add_Edit_Recipe.py"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _fake_draft(ingredient_name: str) -> dict:
    return {
        "name": "Test Recipe",
        "cook_time_minutes": 20,
        "servings": 4,
        "instructions": "Cook it.",
        "ingredients": [{"name": ingredient_name, "quantity": 1, "unit": "each"}],
    }


def _import_via_url(isolated_db, ingredient_name: str) -> AppTest:
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page(ADD_EDIT_PAGE).run()

    at.text_area(key="ai_import_input").set_value("https://example.com/recipe")
    at = at.run()

    with patch.object(recipe_import, "parse_recipe_url", return_value=_fake_draft(ingredient_name)):
        at = [b for b in at.button if b.label == "Import"][0].click().run()
    return at


def test_import_uses_static_dictionary_when_no_override_set(isolated_db):
    at = _import_via_url(isolated_db, "chicken")
    assert not at.exception
    assert at.selectbox(key="ing_cat_1_0").value == "meat"  # categorization.py's static dictionary


def test_import_prefers_override_over_static_dictionary(isolated_db):
    conn = database.get_connection()
    category_overrides.set_override(conn, "chicken", "frozen")
    conn.close()

    at = _import_via_url(isolated_db, "chicken")
    assert not at.exception
    assert at.selectbox(key="ing_cat_1_0").value == "frozen"


def test_import_prefers_override_via_canonical_form(isolated_db):
    """The override applies through canonicalization, not exact string
    match -- correcting 'garlic' also affects a differently-phrased
    ingredient that canonicalizes to the same name."""
    conn = database.get_connection()
    category_overrides.set_override(conn, "garlic", "meat")  # a deliberately odd choice, just to prove it applies
    conn.close()

    at = _import_via_url(isolated_db, "garlic cloves crushed")
    assert not at.exception
    assert at.selectbox(key="ing_cat_1_0").value == "meat"
