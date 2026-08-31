"""
Add/Edit Recipe form, including a repeatable ingredient-rows section and
the recipe's own photo (upload/replace/remove — see docs/PRODUCT_SPEC.md
§14, resized/compressed on save by services/photos.py). This is separate
from photo *import* (extracting a draft from a photo of a cookbook page)
— see docs/PRODUCT_SPEC.md §16b.

Recipe import layers three paths, per docs/PRODUCT_SPEC.md §16 (see
docs/DECISIONS.md for the reasoning):
1. URL structured data (services/recipe_import) — deterministic, no AI
   backend needed at all.
2. AI text fallback (services/ai_assist) — for pasted free text, or a URL
   with no structured data; needs a configured backend (Ollama or
   Gemini).
3. AI photo import (services/ai_assist) — always Gemini; only appears if
   a Gemini key is configured, independent of the text backend setting.

Ingredient category suggestions are also optional AI Assist — see
docs/AGENT_INSTRUCTIONS.md §6. Every AI-dependent control here simply
doesn't appear when its backend isn't configured/reachable; the rest of
this form (including URL import) works identically either way.
"""

import streamlit as st

from database import get_connection
from models import SEASONALITIES, STORE_CATEGORIES
from services import ai_assist, photos, recipe_import
from services.ingredients import list_ingredients, replace_recipe_ingredients
from services.recipes import create_recipe, get_recipe, update_recipe

st.set_page_config(page_title="Add/Edit Recipe — Meal Planner", page_icon="🍽️")

conn = get_connection()

edit_recipe_id = st.session_state.get("edit_recipe_id")
existing = get_recipe(conn, edit_recipe_id) if edit_recipe_id else None

ai_available = ai_assist.is_available()

st.title("Edit Recipe" if existing else "Add Recipe")

import_message = st.session_state.pop("ai_import_message", None)
if import_message:
    st.success(import_message)

# Ingredient rows need their own add/remove buttons, which can't live
# inside a Streamlit form (forms only allow a single submit button), so
# this page uses plain widgets throughout rather than st.form. Rows are
# keyed by a stable counter, not list position, so removing a row can't
# make a leftover widget key show the wrong row's data.
if "ingredient_row_counter" not in st.session_state:
    st.session_state["ingredient_row_counter"] = 0

target_recipe_id = existing.id if existing else "new"
if st.session_state.get("ingredient_rows_for") != target_recipe_id:
    # These core fields carry an explicit key (so an AI import draft can
    # be pushed into them — see below), which means Streamlit will keep
    # showing whatever was last typed unless we clear it here whenever the
    # target recipe changes — the same staleness problem the ingredient
    # rows below already guard against.
    for _key in (
        "af_name",
        "af_cook_time",
        "af_servings",
        "af_instructions",
        "af_photo_upload",
        "af_remove_photo",
    ):
        st.session_state.pop(_key, None)
    rows = []
    if existing:
        for ing in list_ingredients(conn, existing.id):
            st.session_state["ingredient_row_counter"] += 1
            rows.append(
                {
                    "_key": st.session_state["ingredient_row_counter"],
                    "_cat_version": 0,
                    "name": ing.name,
                    "quantity": "" if ing.quantity is None else str(ing.quantity),
                    "unit": ing.unit or "",
                    "store_category": ing.store_category,
                }
            )
    st.session_state["ingredient_rows"] = rows
    st.session_state["ingredient_rows_for"] = target_recipe_id

def _apply_import_draft(draft: dict) -> None:
    """Push an import draft (from URL structured data, AI text fallback,
    or AI photo import) into the form fields and ingredient rows, then
    rerun so it's visible. Never saved automatically — the user still
    reviews everything below before clicking Save Recipe."""
    st.session_state["af_name"] = draft["name"]
    st.session_state["af_cook_time"] = draft["cook_time_minutes"]
    st.session_state["af_servings"] = draft["servings"]
    st.session_state["af_instructions"] = draft["instructions"] or ""

    rows = []
    for ing in draft["ingredients"]:
        st.session_state["ingredient_row_counter"] += 1
        rows.append(
            {
                "_key": st.session_state["ingredient_row_counter"],
                "_cat_version": 0,
                "name": ing["name"],
                "quantity": "" if ing["quantity"] is None else str(ing["quantity"]),
                "unit": ing["unit"] or "",
                "store_category": "other",
            }
        )
    st.session_state["ingredient_rows"] = rows
    st.session_state["ingredient_rows_for"] = target_recipe_id
    st.session_state["ai_import_message"] = (
        f"Imported \"{draft['name']}\" — review and adjust below before saving."
    )
    st.rerun()


if not existing:
    with st.expander("Import a recipe (URL, pasted text, or a photo)"):
        import_input = st.text_area(
            "Recipe URL or pasted text",
            key="ai_import_input",
            placeholder="Paste a recipe URL, or the recipe text itself...",
            height=100,
        )
        if st.button("Import"):
            source = import_input.strip()
            draft = None
            if source.lower().startswith(("http://", "https://")):
                draft = recipe_import.parse_recipe_url(source)  # deterministic, no AI needed
                if draft is None and ai_available:
                    fetched = ai_assist.fetch_url_text(source)
                    draft = ai_assist.import_recipe_from_text(fetched) if fetched else None
            elif source and ai_available:
                draft = ai_assist.import_recipe_from_text(source)

            if draft:
                _apply_import_draft(draft)
            elif not source:
                st.error("Paste a recipe URL or some recipe text first.")
            else:
                st.error(
                    "Couldn't extract a recipe from that — check the text/URL, "
                    "or fill in the form manually below."
                )

        if ai_assist.is_photo_import_available():
            photo = st.file_uploader(
                "Or upload a photo of a recipe (cookbook page, recipe card)",
                type=["jpg", "jpeg", "png"],
            )
            if photo is not None and st.button("Extract from Photo"):
                draft = ai_assist.import_recipe_from_photo(photo.getvalue(), mime_type=photo.type)
                if draft:
                    _apply_import_draft(draft)
                else:
                    st.error(
                        "Couldn't extract a recipe from that photo — try a clearer "
                        "image, or fill in the form manually below."
                    )

st.subheader("Photo")
current_photo_path = existing.photo_path if existing else None
if photos.photo_exists(current_photo_path):
    st.image(str(photos.resolve_photo_path(current_photo_path)), width=200)
    remove_photo = st.checkbox("Remove current photo", key="af_remove_photo")
else:
    remove_photo = False

recipe_photo_upload = st.file_uploader(
    "Replace photo" if photos.photo_exists(current_photo_path) else "Upload a photo",
    type=["jpg", "jpeg", "png"],
    key="af_photo_upload",
)
if recipe_photo_upload is not None:
    try:
        st.image(recipe_photo_upload, width=200, caption="New photo preview")
    except Exception:
        st.warning("That file doesn't look like a valid image.")

st.session_state.setdefault("af_name", existing.name if existing else "")
st.session_state.setdefault("af_cook_time", existing.cook_time_minutes if existing else 30)
st.session_state.setdefault("af_servings", existing.servings if existing else 4)

name = st.text_input("Name", key="af_name")
cook_time_minutes = st.number_input("Cook time (minutes)", min_value=0, step=5, key="af_cook_time")
family_enjoyment = st.slider(
    "Family enjoyment", 1, 5, value=existing.family_enjoyment if existing else 3
)
seasonality = st.selectbox(
    "Seasonality",
    SEASONALITIES,
    index=SEASONALITIES.index(existing.seasonality if existing else "all-season"),
)
is_quick_fallback = st.checkbox(
    "Quick-fallback recipe (near-zero-effort option)",
    value=existing.is_quick_fallback if existing else False,
)
servings = st.number_input("Servings", min_value=1, step=1, key="af_servings")

st.subheader("Ingredients")
for row in st.session_state["ingredient_rows"]:
    key = row["_key"]
    if ai_available:
        cols = st.columns([2.5, 1, 1, 1.5, 0.6, 0.6])
        name_col, qty_col, unit_col, cat_col, suggest_col, remove_col = cols
    else:
        cols = st.columns([3, 1, 1, 2, 1])
        name_col, qty_col, unit_col, cat_col, remove_col = cols
        suggest_col = None

    row["name"] = name_col.text_input("Name", value=row["name"], key=f"ing_name_{key}")
    row["quantity"] = qty_col.text_input("Qty", value=row["quantity"], key=f"ing_qty_{key}")
    row["unit"] = unit_col.text_input("Unit", value=row["unit"], key=f"ing_unit_{key}")
    row["store_category"] = cat_col.selectbox(
        "Category",
        STORE_CATEGORIES,
        index=STORE_CATEGORIES.index(row["store_category"]),
        key=f"ing_cat_{key}_{row.get('_cat_version', 0)}",
    )

    if suggest_col is not None:
        suggest_col.markdown("<br>", unsafe_allow_html=True)
        if suggest_col.button("🤖", key=f"ing_suggest_{key}", help="Suggest category with AI"):
            suggestion = ai_assist.suggest_store_category(row["name"])
            if suggestion:
                row["store_category"] = suggestion
                row["_cat_version"] = row.get("_cat_version", 0) + 1
            st.rerun()

    remove_col.markdown("<br>", unsafe_allow_html=True)
    if remove_col.button("✕", key=f"ing_remove_{key}"):
        st.session_state["ingredient_rows"] = [
            r for r in st.session_state["ingredient_rows"] if r["_key"] != key
        ]
        st.rerun()

if st.button("+ Add Ingredient"):
    st.session_state["ingredient_row_counter"] += 1
    st.session_state["ingredient_rows"].append(
        {
            "_key": st.session_state["ingredient_row_counter"],
            "_cat_version": 0,
            "name": "",
            "quantity": "",
            "unit": "",
            "store_category": "other",
        }
    )
    st.rerun()

st.session_state.setdefault("af_instructions", existing.instructions if existing else "")
instructions = st.text_area("Instructions", height=150, key="af_instructions")
notes = st.text_area("Notes", value=existing.notes if existing else "")

col1, col2 = st.columns(2)
submitted = col1.button("Save Recipe", type="primary")
cancelled = col2.button("Cancel")

if submitted:
    errors = []
    if not name.strip():
        errors.append("Name is required.")

    ingredients = []
    for row in st.session_state["ingredient_rows"]:
        row_name = row["name"].strip()
        if not row_name:
            continue
        quantity = None
        if row["quantity"].strip():
            try:
                quantity = float(row["quantity"])
            except ValueError:
                errors.append(f"Ingredient '{row_name}': quantity must be a number.")
        ingredients.append(
            {
                "name": row_name,
                "quantity": quantity,
                "unit": row["unit"].strip() or None,
                "store_category": row["store_category"],
            }
        )

    if errors:
        for error in errors:
            st.error(error)
    else:
        fields = dict(
            name=name.strip(),
            cook_time_minutes=int(cook_time_minutes),
            family_enjoyment=int(family_enjoyment),
            seasonality=seasonality,
            is_quick_fallback=is_quick_fallback,
            servings=int(servings),
            instructions=instructions or None,
            notes=notes or None,
        )
        if existing:
            update_recipe(conn, existing.id, **fields)
            saved_id = existing.id
        else:
            saved_id = create_recipe(conn, **fields)
        replace_recipe_ingredients(conn, saved_id, ingredients)

        photo_error = None
        if recipe_photo_upload is not None:
            try:
                relative_path = photos.save_recipe_photo(recipe_photo_upload.getvalue(), saved_id)
                update_recipe(conn, saved_id, photo_path=relative_path)
            except Exception:
                photo_error = (
                    "Recipe saved, but that photo couldn't be processed — try a "
                    "different image."
                )
        elif remove_photo:
            photos.delete_recipe_photo(saved_id)
            update_recipe(conn, saved_id, photo_path=None)

        st.session_state["selected_recipe_id"] = saved_id
        st.session_state.pop("edit_recipe_id", None)
        st.session_state.pop("ingredient_rows_for", None)
        if photo_error:
            st.session_state["photo_error_message"] = photo_error
        st.switch_page("pages/3_Recipe_Detail.py")

if cancelled:
    st.session_state.pop("edit_recipe_id", None)
    st.session_state.pop("ingredient_rows_for", None)
    st.switch_page("pages/1_Recipes.py")
