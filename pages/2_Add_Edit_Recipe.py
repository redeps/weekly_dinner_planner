"""
Add/Edit Recipe form. Ingredients (Milestone 2) and photo upload
(Milestone 9) are not part of this form yet — see docs/ROADMAP.md.
"""

import streamlit as st

from database import get_connection
from models import SEASONALITIES
from services.recipes import create_recipe, get_recipe, update_recipe

st.set_page_config(page_title="Add/Edit Recipe — Meal Planner", page_icon="🍽️")

conn = get_connection()

edit_recipe_id = st.session_state.get("edit_recipe_id")
existing = get_recipe(conn, edit_recipe_id) if edit_recipe_id else None

st.title("Edit Recipe" if existing else "Add Recipe")

with st.form("recipe_form"):
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
    instructions = st.text_area(
        "Instructions", value=existing.instructions if existing else "", height=150
    )
    notes = st.text_area("Notes", value=existing.notes if existing else "")

    submitted = st.form_submit_button("Save Recipe")

    if submitted:
        if not name.strip():
            st.error("Name is required.")
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
                st.session_state["selected_recipe_id"] = existing.id
            else:
                new_id = create_recipe(conn, **fields)
                st.session_state["selected_recipe_id"] = new_id
            st.session_state.pop("edit_recipe_id", None)
            st.switch_page("pages/3_Recipe_Detail.py")

if st.button("Cancel"):
    st.session_state.pop("edit_recipe_id", None)
    st.switch_page("pages/1_Recipes.py")
