"""
Milestone 13 Phase 3 durability fix: save_recipe_photo distinguishes a
failed R2 backup (photo saved and usable now, but not durable — raises
photos.PhotoBackupError) from a genuine local processing failure (an
unreadable upload — any other exception). pages/2_Add_Edit_Recipe.py
must show a different, distinguishable warning for each. See
docs/DECISIONS.md — "Phase 3 durability fix" — for the reasoning.

Driven against the real page scripts via AppTest, same pattern as
test_polish_ui.py / test_cook_history_ui.py. Uses both database
isolation (TEST_SCHEMA_IDENTITY) and photo-dir isolation (PHOTOS_DIR) —
this page touches both.
"""

import io
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

import database
from services import photos

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


@pytest.fixture(autouse=True)
def isolated_photos_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTOS_DIR", tmp_path / "photos")


@pytest.fixture
def r2_configured_but_broken(monkeypatch):
    """Simulates st.secrets["r2"] present but every call to it failing —
    matches tests/test_photos_service.py's fixture of the same name/intent."""
    monkeypatch.setattr(photos, "_r2_configured", lambda: True)

    def _raise_client():
        raise RuntimeError("simulated R2 unreachable")

    monkeypatch.setattr(photos, "_r2_client", _raise_client)


def make_jpeg_bytes():
    image = Image.new("RGB", (100, 100), color=(200, 50, 50))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _start_add_recipe(name: str) -> AppTest:
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page(ADD_EDIT_PAGE).run()
    assert not at.exception
    at.text_input(key="af_name").set_value(name)
    return at


def test_r2_sync_failure_shows_distinguishable_warning_and_still_saves_photo(
    isolated_db, r2_configured_but_broken
):
    at = _start_add_recipe("R2 Failure Recipe")
    at.file_uploader(key="af_photo_upload").upload("photo.jpg", make_jpeg_bytes(), "image/jpeg")
    at = at.run()
    assert not at.exception

    save_btn = [b for b in at.button if b.label == "Save Recipe"][0]
    at = save_btn.click().run()  # this click's own rerun follows the page's internal
    assert not at.exception  # st.switch_page() to Recipe Detail — verified directly:
    # `at` here already reflects Recipe Detail's render (its title matches
    # the just-saved recipe's name), no separate switch_page call needed.

    recipe_id = at.session_state["selected_recipe_id"]
    warnings = [w.value for w in at.warning]
    assert any("couldn't be backed up" in w and "restart" in w for w in warnings), warnings
    assert not any("couldn't be processed" in w for w in warnings), (
        "the R2-sync-failure case must not show the generic "
        "processing-failure message"
    )

    conn = database.get_connection()
    photo_path = conn.execute(
        "SELECT photo_path FROM recipes WHERE id = %s", (recipe_id,)
    ).fetchone()[0]
    conn.close()
    assert photo_path == "photos/{}.jpg".format(recipe_id)
    assert photos.resolve_photo_path(photo_path).is_file(), (
        "the local copy must still be saved and usable even though the R2 "
        "backup failed"
    )


def test_pure_local_failure_still_shows_generic_message(isolated_db):
    at = _start_add_recipe("Local Failure Recipe")
    at.file_uploader(key="af_photo_upload").upload("photo.jpg", b"not a real image", "image/jpeg")
    at = at.run()
    assert not at.exception

    save_btn = [b for b in at.button if b.label == "Save Recipe"][0]
    at = save_btn.click().run()
    assert not at.exception

    warnings = [w.value for w in at.warning]
    assert any("couldn't be processed" in w for w in warnings), warnings
    assert not any("backed up" in w for w in warnings), (
        "a genuine local processing failure must not show the R2-specific "
        "backup-failure message"
    )
