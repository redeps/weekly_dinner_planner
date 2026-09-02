"""
Recipes browsing screen — search, filter by season / quick-fallback, and
browse recipe cards. See docs/PRODUCT_SPEC.md §15.
"""

import streamlit as st

from database import get_connection
from models import SEASONALITIES
from services import photos
from services.auth import require_password
from services.recipes import list_recipes

st.set_page_config(page_title="Recipes — Meal Planner", page_icon="🍽️")
require_password()

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
    if list_recipes(conn):
        st.info("No recipes match your filters — try adjusting search, season, or quick-fallback.")
    else:
        st.info("You haven't added any recipes yet — click **+ Add Recipe** above to get started.")
else:
    for recipe in recipes:
        with st.container(border=True):
            cols = st.columns([1, 3, 1])
            with cols[0]:
                if photos.photo_exists(recipe.photo_path):
                    st.image(str(photos.resolve_photo_path(recipe.photo_path)), caption=recipe.name)
            with cols[1]:
                title = recipe.name
                if recipe.is_quick_fallback:
                    title += " ⚡"
                st.subheader(title)
                st.caption(
                    f"{recipe.cook_time_minutes} min · "
                    f"{'⭐' * recipe.family_enjoyment} · "
                    f"{recipe.seasonality}"
                )
            with cols[2]:
                if st.button("View", key=f"view_{recipe.id}"):
                    st.session_state["selected_recipe_id"] = recipe.id
                    # Generic browsing has no day context — clear any
                    # stale plan-day id left over from an earlier
                    # Week-Plan-originated visit, or this recipe would
                    # incorrectly show a scaled amount from a different
                    # day (see docs/DECISIONS.md).
                    st.session_state.pop("selected_plan_day_id", None)
                    st.switch_page("pages/3_Recipe_Detail.py")
