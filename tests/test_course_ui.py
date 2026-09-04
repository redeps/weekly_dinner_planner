"""
Milestone 16 Phase 1: the `course` field on recipes (main/side/dessert) --
Add/Edit Recipe's course selectbox and Recipes browsing's course filter +
badge. See docs/DECISIONS.md and docs/ROADMAP.md. Uses streamlit.testing.v1
AppTest, same isolated-schema pattern as tests/test_photo_backup_ui.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import database
from services.recipes import create_recipe, get_recipe

REPO = Path(__file__).parent.parent
HOME_PAGE = str(REPO / "app.py")
ADD_EDIT_PAGE = "pages/2_Add_Edit_Recipe.py"
RECIPES_PAGE = str(REPO / "pages" / "1_Recipes.py")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "TEST_SCHEMA_IDENTITY", tmp_path)
    yield
    schema = database.schema_name_for(tmp_path)
    conn = database.get_connection()
    conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _course_selectbox(at):
    return [sb for sb in at.selectbox if sb.label == "Course"][0]


# --- Add/Edit Recipe: course selectbox ---


def test_add_recipe_course_defaults_to_main(isolated_db):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page(ADD_EDIT_PAGE).run()
    assert not at.exception
    assert _course_selectbox(at).value == "main"


def test_saving_a_side_recipe_persists_its_course(isolated_db):
    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at = at.switch_page(ADD_EDIT_PAGE).run()

    at.text_input(key="af_name").set_value("Yorkshire Pudding")
    _course_selectbox(at).set_value("side")
    at = at.run()

    save_btn = [b for b in at.button if b.label == "Save Recipe"][0]
    at = save_btn.click().run()
    assert not at.exception

    recipe_id = at.session_state["selected_recipe_id"]
    conn = database.get_connection()
    recipe = get_recipe(conn, recipe_id)
    conn.close()
    assert recipe.course == "side"


def test_editing_an_existing_recipe_shows_its_current_course(isolated_db):
    conn = database.get_connection()
    recipe_id = create_recipe(
        conn,
        name="Apple Crumble",
        cook_time_minutes=45,
        family_enjoyment=4,
        seasonality="fall",
        servings=6,
        course="dessert",
    )
    conn.close()

    at = AppTest.from_file(HOME_PAGE)
    at.session_state["authenticated"] = True
    at = at.run()
    at.session_state["edit_recipe_id"] = recipe_id
    at = at.switch_page(ADD_EDIT_PAGE).run()

    assert not at.exception
    assert _course_selectbox(at).value == "dessert"


# --- Recipes browsing: course filter + badge ---


def _make_recipes(conn):
    create_recipe(
        conn,
        name="Roast Chicken",
        cook_time_minutes=90,
        family_enjoyment=5,
        seasonality="all-season",
        servings=4,
        course="main",
    )
    create_recipe(
        conn,
        name="Garden Salad",
        cook_time_minutes=10,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
        course="side",
    )
    create_recipe(
        conn,
        name="Apple Crumble",
        cook_time_minutes=45,
        family_enjoyment=4,
        seasonality="fall",
        servings=6,
        course="dessert",
    )


def _load_recipes_page(isolated_db) -> AppTest:
    at = AppTest.from_file(RECIPES_PAGE)
    at.session_state["authenticated"] = True
    return at.run()


def test_course_filter_options_include_all_courses(isolated_db):
    conn = database.get_connection()
    _make_recipes(conn)
    conn.close()

    at = _load_recipes_page(isolated_db)
    course_filter = [sb for sb in at.selectbox if sb.label == "Course"][0]
    assert course_filter.options == ["All", "main", "side", "dessert"]


def test_filtering_by_course_narrows_the_list(isolated_db):
    conn = database.get_connection()
    _make_recipes(conn)
    conn.close()

    at = _load_recipes_page(isolated_db)
    course_filter = [sb for sb in at.selectbox if sb.label == "Course"][0]
    at = course_filter.set_value("side").run()

    assert not at.exception
    titles = [s.value for s in at.subheader]
    assert titles == ["Garden Salad"]


def test_main_recipe_card_shows_no_course_badge(isolated_db):
    conn = database.get_connection()
    _make_recipes(conn)
    conn.close()

    at = _load_recipes_page(isolated_db)
    captions = [c.value for c in at.caption]
    main_caption = next(c for c in captions if "90 min" in c)
    assert not main_caption.endswith("· main")
    assert not main_caption.endswith("· side")
    assert not main_caption.endswith("· dessert")


def test_side_and_dessert_cards_show_course_badge(isolated_db):
    conn = database.get_connection()
    _make_recipes(conn)
    conn.close()

    at = _load_recipes_page(isolated_db)
    captions = [c.value for c in at.caption]
    side_caption = next(c for c in captions if "10 min" in c)
    dessert_caption = next(c for c in captions if "45 min" in c)
    assert side_caption.endswith("· side")
    assert dessert_caption.endswith("· dessert")
