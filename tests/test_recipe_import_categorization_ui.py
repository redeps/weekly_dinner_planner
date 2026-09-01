"""
Auto-categorize imported ingredients (pages/2_Add_Edit_Recipe.py).

Neither import path (services/recipe_import.py's JSON-LD parser, nor
services/ai_assist.py's text/photo drafts) ever produces a
store_category — every imported row lands as "other" by default (see
_apply_import_draft). This is a deliberate, explicit, skippable action —
a "🤖 Auto-categorize ingredients" button shown once an import has
happened, wired only into this page (not into recipe_import.py or
ai_assist.py's draft builders), same isolation boundary as the existing
per-row 🤖 suggest button. It only touches rows still at the "other"
default, never a category the user already picked by hand, and degrades
gracefully (rows stay "other") if suggest_store_category returns None or
no AI backend is configured — same reviewability guarantee as the rest of
this form: nothing here is ever auto-saved.

Driven against the real page script via AppTest, same pattern as
test_photo_backup_ui.py. ai_assist itself is mocked throughout (patched
at the module level pages/2_Add_Edit_Recipe.py calls through) — no real
Ollama/Gemini server is contacted.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import database
from services import ai_assist

REPO = Path(__file__).parent.parent
ADD_EDIT_PAGE = str(REPO / "pages" / "2_Add_Edit_Recipe.py")

BUTTON_LABEL = "🤖 Auto-categorize ingredients"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _add_page_with_imported_rows(rows: list[dict]) -> AppTest:
    """An Add-mode page whose ingredient rows are already populated as if
    _apply_import_draft() had just run (import_happened=True, every
    imported row defaulted to "other") — bypasses the actual network/
    parsing calls, which are covered separately in
    test_recipe_import_service.py and test_ai_assist_service.py."""
    at = AppTest.from_file(ADD_EDIT_PAGE)
    at.session_state["authenticated"] = True
    at.session_state["ingredient_rows_for"] = "new"
    at.session_state["ingredient_row_counter"] = len(rows)
    at.session_state["ingredient_rows"] = rows
    at.session_state["import_happened"] = True
    return at


def _click(at: AppTest, label: str) -> AppTest:
    return [b for b in at.button if b.label == label][0].click().run()


def test_auto_categorize_fills_only_other_defaulted_rows(isolated_db):
    rows = [
        {"_key": 1, "_cat_version": 0, "name": "onion", "quantity": "1", "unit": "", "store_category": "other"},
        {"_key": 2, "_cat_version": 0, "name": "milk", "quantity": "1", "unit": "cup", "store_category": "other"},
    ]
    suggestions = {"onion": "produce", "milk": "dairy"}

    with patch.object(ai_assist, "is_available", return_value=True):
        at = _add_page_with_imported_rows(rows)
        at = at.run()
        assert not at.exception

        with patch.object(
            ai_assist, "suggest_store_category", side_effect=lambda name, **kw: suggestions.get(name)
        ) as mock_suggest:
            at = _click(at, BUTTON_LABEL)

    assert not at.exception
    updated = {r["name"]: r["store_category"] for r in at.session_state["ingredient_rows"]}
    assert updated == {"onion": "produce", "milk": "dairy"}
    assert mock_suggest.call_count == 2


def test_auto_categorize_leaves_a_user_edited_category_untouched(isolated_db):
    rows = [
        {"_key": 1, "_cat_version": 0, "name": "onion", "quantity": "1", "unit": "", "store_category": "other"},
        # user already picked a category by hand before clicking the action
        {"_key": 2, "_cat_version": 1, "name": "salt", "quantity": "1", "unit": "tsp", "store_category": "pantry"},
    ]

    with patch.object(ai_assist, "is_available", return_value=True):
        at = _add_page_with_imported_rows(rows)
        at = at.run()
        assert not at.exception

        with patch.object(
            ai_assist, "suggest_store_category", return_value="produce"
        ) as mock_suggest:
            at = _click(at, BUTTON_LABEL)

    assert not at.exception
    updated = {r["name"]: r["store_category"] for r in at.session_state["ingredient_rows"]}
    assert updated["onion"] == "produce"
    assert updated["salt"] == "pantry", "a category the user already set by hand must not be overwritten"
    mock_suggest.assert_called_once_with("onion")


def test_auto_categorize_degrades_gracefully_when_suggestion_is_none(isolated_db):
    rows = [
        {"_key": 1, "_cat_version": 0, "name": "mystery ingredient", "quantity": "", "unit": "", "store_category": "other"},
    ]

    with patch.object(ai_assist, "is_available", return_value=True):
        at = _add_page_with_imported_rows(rows)
        at = at.run()
        assert not at.exception

        with patch.object(ai_assist, "suggest_store_category", return_value=None):
            at = _click(at, BUTTON_LABEL)

    assert not at.exception
    updated = {r["name"]: r["store_category"] for r in at.session_state["ingredient_rows"]}
    assert updated["mystery ingredient"] == "other"


def test_auto_categorize_action_does_not_render_when_ai_unavailable(isolated_db):
    rows = [
        {"_key": 1, "_cat_version": 0, "name": "onion", "quantity": "1", "unit": "", "store_category": "other"},
    ]

    with patch.object(ai_assist, "is_available", return_value=False):
        at = _add_page_with_imported_rows(rows)
        at = at.run()

    assert not at.exception
    assert [b for b in at.button if b.label == BUTTON_LABEL] == []
