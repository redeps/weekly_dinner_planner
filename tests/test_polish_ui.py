"""
Milestone 12 tests: confirmation dialogs, empty-state wording, and backup
export, driven against the actual page scripts via AppTest.

Uses an isolated database (database.TEST_SCHEMA_IDENTITY monkeypatched to
a per-test Postgres schema), same pattern as test_cook_history_ui.py —
never touches the real `public` schema.
"""

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import database
from services import ai_assist
from services.recipes import create_recipe, get_recipe

REPO = Path(__file__).parent.parent
RECIPES_PAGE = str(REPO / "pages" / "1_Recipes.py")
RECIPE_DETAIL_PAGE = str(REPO / "pages" / "3_Recipe_Detail.py")
HOME_PAGE = str(REPO / "app.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


@pytest.fixture
def recipe_id(isolated_db):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name="Deactivate Me",
        cook_time_minutes=20,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    conn.close()
    return recipe_id


# --- Deactivate requires confirmation ---


def test_clicking_deactivate_alone_does_not_deactivate(recipe_id):
    at = AppTest.from_file(RECIPE_DETAIL_PAGE)
    at.session_state["authenticated"] = True
    at.session_state["selected_recipe_id"] = recipe_id
    at = at.run()

    at = [b for b in at.button if b.label == "Deactivate"][0].click().run()
    assert not at.exception

    conn = database.get_connection()
    recipe = get_recipe(conn, recipe_id)
    conn.close()
    assert recipe.active is True, "one click on Deactivate must not deactivate by itself"
    assert any("Deactivate" in w.value for w in at.warning)


def test_confirming_deactivate_actually_deactivates(recipe_id):
    # Goes through app.py, unlike the other tests here: this one's "Yes,
    # deactivate" click triggers st.switch_page(), which AppTest can only
    # resolve correctly when the session started from the real entrypoint
    # (a known AppTest limitation, not an app bug).
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at.session_state["selected_recipe_id"] = recipe_id
    at = at.switch_page(RECIPE_DETAIL_PAGE.replace(str(REPO) + "/", "")).run()

    at = [b for b in at.button if b.label == "Deactivate"][0].click().run()
    at = [b for b in at.button if b.label == "Yes, deactivate"][0].click().run()
    assert not at.exception

    conn = database.get_connection()
    recipe = get_recipe(conn, recipe_id)
    conn.close()
    assert recipe.active is False


def test_cancelling_deactivate_leaves_recipe_active(recipe_id):
    at = AppTest.from_file(RECIPE_DETAIL_PAGE)
    at.session_state["authenticated"] = True
    at.session_state["selected_recipe_id"] = recipe_id
    at = at.run()

    at = [b for b in at.button if b.label == "Deactivate"][0].click().run()
    at = [b for b in at.button if b.label == "Cancel"][0].click().run()
    assert not at.exception
    assert [b for b in at.button if b.label == "Yes, deactivate"] == []

    conn = database.get_connection()
    recipe = get_recipe(conn, recipe_id)
    conn.close()
    assert recipe.active is True


def test_rerendering_after_deactivate_click_does_not_deactivate(recipe_id):
    """The same duplicate-action concern as history writes: re-rendering
    while the confirmation is pending must not itself trigger the
    destructive action."""
    at = AppTest.from_file(RECIPE_DETAIL_PAGE)
    at.session_state["authenticated"] = True
    at.session_state["selected_recipe_id"] = recipe_id
    at = at.run()
    at = [b for b in at.button if b.label == "Deactivate"][0].click().run()

    for _ in range(3):
        at = at.run()
        assert not at.exception

    conn = database.get_connection()
    recipe = get_recipe(conn, recipe_id)
    conn.close()
    assert recipe.active is True


# --- Empty-state wording distinguishes "no recipes" from "no matches" ---


def test_recipes_page_shows_get_started_message_when_database_is_empty(isolated_db):
    at = AppTest.from_file(RECIPES_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    assert not at.exception
    infos = [i.value for i in at.info]
    assert any("haven't added any recipes yet" in i for i in infos)
    assert not any("match your filters" in i for i in infos)


def test_recipes_page_shows_filter_message_when_recipes_exist_but_filtered_out(recipe_id):
    at = AppTest.from_file(RECIPES_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    search_box = [w for w in at.text_input if w.label == "Search"][0]
    at = search_box.set_value("no such recipe name").run()
    assert not at.exception
    infos = [i.value for i in at.info]
    assert any("match your filters" in i for i in infos)
    assert not any("haven't added any recipes yet" in i for i in infos)


# --- Backup export ---


def test_home_page_offers_a_backup_download(isolated_db):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    assert not at.exception
    download_buttons = at.download_button
    assert len(download_buttons) == 1
    assert download_buttons[0].label == "Download Backup (.zip)"


# --- Home page "+ Add Recipe" button ---


def test_add_recipe_button_navigates_to_blank_add_form(isolated_db):
    # Goes through app.py, unlike most other tests here: the button's
    # click triggers st.switch_page(), which AppTest can only resolve
    # correctly when the session started from the real entrypoint (same
    # reasoning as test_confirming_deactivate_actually_deactivates above).
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()

    at = [b for b in at.button if b.label == "+ Add Recipe"][0].click().run()
    assert not at.exception
    assert at.title[0].value == "Add Recipe"
    assert at.text_input(key="af_name").value == ""


def test_add_recipe_button_does_not_carry_over_a_stale_edit_recipe_id(recipe_id):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at.session_state["edit_recipe_id"] = recipe_id  # simulates a leftover Edit-mode visit

    at = [b for b in at.button if b.label == "+ Add Recipe"][0].click().run()
    assert not at.exception
    assert at.title[0].value == "Add Recipe"
    assert at.text_input(key="af_name").value == ""
    assert "edit_recipe_id" not in at.session_state


def test_backup_download_contains_valid_data(recipe_id):
    exported = database.export_database_bytes()

    with zipfile.ZipFile(io.BytesIO(exported)) as zf:
        recipes_csv = zf.read("recipes.csv").decode()

    assert "Deactivate Me" in recipes_csv


# --- Home page surfaces ai_assist.backend_status_note() ---


def test_home_page_shows_backend_status_note_when_misconfigured(isolated_db):
    with patch.object(
        ai_assist, "backend_status_note", return_value="GEMINI_API_KEY is set but ..."
    ):
        at = AppTest.from_file(HOME_PAGE)
        at.session_state["authenticated"] = True
        at = at.run()

    assert not at.exception
    assert any("GEMINI_API_KEY is set" in c.value for c in at.caption)


def test_home_page_shows_no_backend_status_note_when_fine(isolated_db):
    with patch.object(ai_assist, "backend_status_note", return_value=None):
        at = AppTest.from_file(HOME_PAGE)
        at.session_state["authenticated"] = True
        at = at.run()

    assert not at.exception
    assert not any("AI_ASSIST_BACKEND" in c.value for c in at.caption)
