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
    assert any("Couldn't extract a recipe from that" in e for e in errors), errors


# --- Extract from Photo: multi-photo cap ---


def test_more_than_three_photos_shows_cap_error_and_hides_extract_button(isolated_db):
    """Uploading more than MAX_IMPORT_PHOTOS (3) shows an error instead of
    silently truncating or processing all of them — this is meant for a
    handful of photos of one recipe (e.g. front/back of a card), not bulk
    import."""
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        at = _load_add_recipe_page()
        uploader = at.file_uploader(key="ai_import_photo")
        for i in range(4):
            uploader.upload(f"page{i}.jpg", b"fake jpeg bytes", "image/jpeg")
        at = at.run()
        assert not at.exception

    errors = [e.value for e in at.error]
    assert any("at most 3 photos" in e for e in errors), errors
    assert [b for b in at.button if b.label == "Extract from Photo"] == []


def test_three_photos_is_within_the_cap(isolated_db):
    """Exactly MAX_IMPORT_PHOTOS (3) is allowed — the cap error is
    specifically ">3", not ">=3"."""
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        at = _load_add_recipe_page()
        uploader = at.file_uploader(key="ai_import_photo")
        for i in range(3):
            uploader.upload(f"page{i}.jpg", b"fake jpeg bytes", "image/jpeg")
        at = at.run()
        assert not at.exception

    errors = [e.value for e in at.error]
    assert not any("at most 3 photos" in e for e in errors), errors
    assert [b for b in at.button if b.label == "Extract from Photo"] != []


def test_extract_from_photo_combines_multiple_uploaded_photos(isolated_db):
    """All uploaded photos reach import_recipe_from_photos() as one call,
    not one call per photo — driven through the real widget, not a direct
    function call."""
    fake_response = (
        '{"name": "Combined Recipe", "servings": 4, "cook_time_minutes": 20, '
        '"instructions": "Do it.", "ingredients": []}'
    )
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini", return_value=fake_response
    ) as mock_gemini:
        at = _load_add_recipe_page()
        uploader = at.file_uploader(key="ai_import_photo")
        uploader.upload("front.jpg", b"front bytes", "image/jpeg")
        uploader.upload("back.jpg", b"back bytes", "image/jpeg")
        at = at.run()
        assert not at.exception

        at = [b for b in at.button if b.label == "Extract from Photo"][0].click().run()

    assert not at.exception
    mock_gemini.assert_called_once()
    parts = mock_gemini.call_args.args[0]
    inline_parts = [p for p in parts if "inline_data" in p]
    assert len(inline_parts) == 2
    successes = [s.value for s in at.success]
    assert any("Combined Recipe" in s for s in successes), successes
