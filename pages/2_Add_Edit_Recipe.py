"""
Add/Edit Recipe form, including a repeatable ingredient-rows section.
Photo upload (Milestone 9) is not part of this form yet — see
docs/ROADMAP.md.
"""

import streamlit as st

from database import get_connection
from models import SEASONALITIES, STORE_CATEGORIES
from services.ingredients import list_ingredients, replace_recipe_ingredients
from services.recipes import create_recipe, get_recipe, update_recipe

st.set_page_config(page_title="Add/Edit Recipe — Meal Planner", page_icon="🍽️")

conn = get_connection()

edit_recipe_id = st.session_state.get("edit_recipe_id")
existing = get_recipe(conn, edit_recipe_id) if edit_recipe_id else None

st.title("Edit Recipe" if existing else "Add Recipe")

# Ingredient rows need their own add/remove buttons, which can't live
# inside a Streamlit form (forms only allow a single submit button), so
# this page uses plain widgets throughout rather than st.form. Rows are
# keyed by a stable counter, not list position, so removing a row can't
# make a leftover widget key show the wrong row's data.
if "ingredient_row_counter" not in st.session_state:
    st.session_state["ingredient_row_counter"] = 0

target_recipe_id = existing.id if existing else "new"
if st.session_state.get("ingredient_rows_for") != target_recipe_id:
    rows = []
    if existing:
        for ing in list_ingredients(conn, existing.id):
            st.session_state["ingredient_row_counter"] += 1
            rows.append(
                {
                    "_key": st.session_state["ingredient_row_counter"],
                    "name": ing.name,
                    "quantity": "" if ing.quantity is None else str(ing.quantity),
                    "unit": ing.unit or "",
                    "store_category": ing.store_category,
                }
            )
    st.session_state["ingredient_rows"] = rows
    st.session_state["ingredient_rows_for"] = target_recipe_id

name = st.text_input("Name", value=existing.name if existing else "")
cook_time_minutes = st.number_input(
    "Cook time (minutes)",
    min_value=0,
    step=5,
    value=existing.cook_time_minutes if existing else 30,
)
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
servings = st.number_input(
    "Servings", min_value=1, step=1, value=existing.servings if existing else 4
)

st.subheader("Ingredients")
for row in st.session_state["ingredient_rows"]:
    key = row["_key"]
    cols = st.columns([3, 1, 1, 2, 1])
    row["name"] = cols[0].text_input("Name", value=row["name"], key=f"ing_name_{key}")
    row["quantity"] = cols[1].text_input("Qty", value=row["quantity"], key=f"ing_qty_{key}")
    row["unit"] = cols[2].text_input("Unit", value=row["unit"], key=f"ing_unit_{key}")
    row["store_category"] = cols[3].selectbox(
        "Category",
        STORE_CATEGORIES,
        index=STORE_CATEGORIES.index(row["store_category"]),
        key=f"ing_cat_{key}",
    )
    cols[4].markdown("<br>", unsafe_allow_html=True)
    if cols[4].button("✕", key=f"ing_remove_{key}"):
        st.session_state["ingredient_rows"] = [
            r for r in st.session_state["ingredient_rows"] if r["_key"] != key
        ]
        st.rerun()

if st.button("+ Add Ingredient"):
    st.session_state["ingredient_row_counter"] += 1
    st.session_state["ingredient_rows"].append(
        {
            "_key": st.session_state["ingredient_row_counter"],
            "name": "",
            "quantity": "",
            "unit": "",
            "store_category": "other",
        }
    )
    st.rerun()

instructions = st.text_area(
    "Instructions", value=existing.instructions if existing else "", height=150
)
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
        st.session_state["selected_recipe_id"] = saved_id
        st.session_state.pop("edit_recipe_id", None)
        st.session_state.pop("ingredient_rows_for", None)
        st.switch_page("pages/3_Recipe_Detail.py")

if cancelled:
    st.session_state.pop("edit_recipe_id", None)
    st.session_state.pop("ingredient_rows_for", None)
    st.switch_page("pages/1_Recipes.py")
