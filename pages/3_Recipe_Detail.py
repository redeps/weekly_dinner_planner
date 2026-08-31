"""
Recipe Detail screen — full recipe view, edit and deactivate actions. See
docs/PRODUCT_SPEC.md §15. Swap (Milestone 5) is not part of this screen yet.
"""

import streamlit as st

from database import get_connection
from services.ingredients import list_ingredients
from services.recipes import deactivate_recipe, get_recipe

st.set_page_config(page_title="Recipe Detail — Meal Planner", page_icon="🍽️")

conn = get_connection()

recipe_id = st.session_state.get("selected_recipe_id")
recipe = get_recipe(conn, recipe_id) if recipe_id else None

if not recipe:
    st.warning("No recipe selected.")
    if st.button("← Back to Recipes"):
        st.switch_page("pages/1_Recipes.py")
    st.stop()

st.title(recipe.name)

badges = f"{recipe.cook_time_minutes} min · {'⭐' * recipe.family_enjoyment} · {recipe.seasonality}"
if recipe.is_quick_fallback:
    badges += " · ⚡ quick fallback"
st.caption(badges)

if st.button("▶ Start Cooking", type="primary"):
    st.session_state["selected_recipe_id"] = recipe.id
    st.switch_page("pages/8_Cook_Mode.py")

st.write(f"**Servings:** {recipe.servings}")

st.subheader("Ingredients")
ingredients = list_ingredients(conn, recipe.id)
if not ingredients:
    st.write("_No ingredients listed._")
else:
    for ingredient in ingredients:
        amount = " ".join(
            part
            for part in (
                "" if ingredient.quantity is None else f"{ingredient.quantity:g}",
                ingredient.unit or "",
            )
            if part
        )
        line = f"{amount} {ingredient.name}".strip() if amount else ingredient.name
        st.write(f"- {line}")

st.subheader("Instructions")
st.write(recipe.instructions or "_No instructions yet._")

st.subheader("Notes")
st.write(recipe.notes or "_No notes._")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Edit"):
        st.session_state["edit_recipe_id"] = recipe.id
        st.switch_page("pages/2_Add_Edit_Recipe.py")
with col2:
    if st.button("Deactivate"):
        deactivate_recipe(conn, recipe.id)
        st.session_state.pop("selected_recipe_id", None)
        st.switch_page("pages/1_Recipes.py")
with col3:
    if st.button("← Back to Recipes"):
        st.switch_page("pages/1_Recipes.py")
