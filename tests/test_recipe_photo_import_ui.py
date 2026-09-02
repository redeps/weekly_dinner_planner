"""
Add/Edit Recipe's AI photo-import flow (distinct from the recipe's own
display photo further down the page — see services/photos.py and
tests/test_photo_backup_ui.py for that one).

Covers two fixes made after investigating a reported bug:

1. Clicking "Import" (the shared text/URL button) while a photo is
   uploaded into the separate "Or upload a photo to auto-fill this form"
   widget used to show "Paste a recipe URL or some recipe text first." —
   misleading, since a photo *was* provided, just not to this button.
   "Import" only ever reads the text field; it now points the user at
   "Extract from Photo" instead when it detects an uploaded photo.
2. GEMINI_MODEL's old default ("gemini-2.0-flash") had gone stale —
   confirmed via a real API call returning HTTP 404 Not Found — meaning
   every photo import was silently failing already-existing graceful
   degradation (ai_assist._call_gemini() never raises). This proves that
   *specific* failure shape (a 404 from the model endpoint, not just a
   generic mocked None) still degrades to the page's existing message
   rather than crashing.

See docs/DECISIONS.md for the full investigation and fix record.
"""

import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import database
from services import ai_assist

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


def _load_add_recipe_page() -> AppTest:
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page(ADD_EDIT_PAGE).run()
    assert not at.exception
    return at


# --- Import button: photo-aware error message ---


def test_import_with_photo_uploaded_and_no_text_points_at_extract_button(isolated_db):
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        at = _load_add_recipe_page()
        at.file_uploader(key="ai_import_photo").upload(
            "recipe.jpg", b"fake jpeg bytes", "image/jpeg"
        )
        at = at.run()
        assert not at.exception

        at = [b for b in at.button if b.label == "Import"][0].click().run()
        assert not at.exception

    errors = [e.value for e in at.error]
    assert any("Extract from Photo" in e for e in errors), errors
    assert not any("Paste a recipe URL or some recipe text first." in e for e in errors), errors


def test_import_with_no_photo_and_no_text_shows_original_message(isolated_db):
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        at = _load_add_recipe_page()
        at = [b for b in at.button if b.label == "Import"][0].click().run()
        assert not at.exception

    errors = [e.value for e in at.error]
    assert any(e == "Paste a recipe URL or some recipe text first." for e in errors), errors


# --- Extract from Photo: a 404 from the model endpoint degrades gracefully ---


def test_extract_from_photo_degrades_gracefully_on_404_from_model_endpoint(isolated_db):
    """Reproduces the actual failure found while investigating the report:
    GEMINI_MODEL's old default no longer exists, so the real API call
    returned HTTP 404. ai_assist._call_gemini() catches this (returns
    None), but that was only ever proven in the abstract (a plain mocked
    None) — this drives the real page's "Extract from Photo" button with
    urllib.request.urlopen mocked to raise the exact HTTPError shape a
    dead model name produces, confirming the page still shows its
    existing graceful message rather than crashing."""
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        at = _load_add_recipe_page()
        at.file_uploader(key="ai_import_photo").upload(
            "recipe.jpg", b"fake jpeg bytes", "image/jpeg"
        )
        at = at.run()
        assert not at.exception

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://generativelanguage.googleapis.com/...", 404, "Not Found", None, None
            ),
        ):
            at = [b for b in at.button if b.label == "Extract from Photo"][0].click().run()

    assert not at.exception
    errors = [e.value for e in at.error]
    assert any("Couldn't extract a recipe from that photo" in e for e in errors), errors
