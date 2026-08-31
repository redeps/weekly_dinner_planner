"""
Recipes browsing screen — search, filter by season / quick-fallback, and
browse recipe cards. See docs/PRODUCT_SPEC.md §15.
"""

import streamlit as st

from database import get_connection
from models import SEASONALITIES
from services.recipes import list_recipes

st.set_page_config(page_title="Recipes — Meal Planner", page_icon="🍽️")

conn = get_connection()

st.title("Recipes")

if st.button("+ Add Recipe"):
    st.session_state.pop("edit_recipe_id", None)
    st.switch_page("pages/2_Add_Edit_Recipe.py")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    search = st.text_input("Search", placeholder="Search by name")
with col2:
    season = st.selectbox("Season", ["All"] + list(SEASONALITIES))
with col3:
    quick_only = st.checkbox("Quick-fallback only")

recipes = list_recipes(
    conn,
    search=search or None,
    season=None if season == "All" else season,
    quick_fallback_only=quick_only,
)

if not recipes:
    st.info("No recipes match your filters yet.")
else:
    for recipe in recipes:
        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                title = recipe.name
                if recipe.is_quick_fallback:
                    title += " ⚡"
                st.subheader(title)
                st.caption(
                    f"{recipe.cook_time_minutes} min · "
                    f"{'⭐' * recipe.family_enjoyment} · "
                    f"{recipe.seasonality}"
                )
            with cols[1]:
                if st.button("View", key=f"view_{recipe.id}"):
                    st.session_state["selected_recipe_id"] = recipe.id
                    st.switch_page("pages/3_Recipe_Detail.py")
