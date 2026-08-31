"""
Milestone 12 tests: confirmation dialogs, empty-state wording, and backup
export, driven against the actual page scripts via AppTest.

Uses an isolated database (database.DATA_DIR/DB_PATH monkeypatched to a
temp file), same pattern as test_cook_history_ui.py — never touches the
real data/ directory.
"""

import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.recipes import create_recipe, get_recipe

REPO = Path(__file__).parent.parent
RECIPES_PAGE = str(REPO / "pages" / "1_Recipes.py")
RECIPE_DETAIL_PAGE = str(REPO / "pages" / "3_Recipe_Detail.py")
HOME_PAGE = str(REPO / "app.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")


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
    at = AppTest.from_file(HOME_PAGE).run()
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
    at = AppTest.from_file(RECIPES_PAGE).run()
    assert not at.exception
    infos = [i.value for i in at.info]
    assert any("haven't added any recipes yet" in i for i in infos)
    assert not any("match your filters" in i for i in infos)


def test_recipes_page_shows_filter_message_when_recipes_exist_but_filtered_out(recipe_id):
    at = AppTest.from_file(RECIPES_PAGE).run()
    search_box = [w for w in at.text_input if w.label == "Search"][0]
    at = search_box.set_value("no such recipe name").run()
    assert not at.exception
    infos = [i.value for i in at.info]
    assert any("match your filters" in i for i in infos)
    assert not any("haven't added any recipes yet" in i for i in infos)


# --- Backup export ---


def test_home_page_offers_a_backup_download(isolated_db):
    at = AppTest.from_file(HOME_PAGE).run()
    assert not at.exception
    download_buttons = at.download_button
    assert len(download_buttons) == 1
    assert download_buttons[0].label == "Download Backup (.db)"


def test_backup_download_contains_valid_sqlite_data(recipe_id, tmp_path):
    exported = database.export_database_bytes()
    backup_path = tmp_path / "backup_check.db"
    backup_path.write_bytes(exported)

    conn = sqlite3.connect(backup_path)
    names = [row[0] for row in conn.execute("SELECT name FROM recipes WHERE name = 'Deactivate Me'")]
    conn.close()
    assert names == ["Deactivate Me"]
