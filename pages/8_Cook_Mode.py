"""
Cook Mode — a distraction-free, large-font, step-by-step view of a single
recipe's instructions, meant to be read at a glance while actually
cooking. See docs/PRODUCT_SPEC.md §12. Read-only: no editing happens here;
corrections go through the normal Edit Recipe form.

Steps are derived by splitting the recipe's existing `instructions` text
at render time — no new schema, see docs/DATA_MODEL.md and
services/cook_mode.py.
"""

import streamlit as st

from database import get_connection
from services import photos
from services.cook_mode import split_instructions_into_steps
from services.ingredients import list_ingredients
from services.recipes import get_recipe

st.set_page_config(
    page_title="Cook Mode — Meal Planner",
    page_icon="🍽️",
    initial_sidebar_state="collapsed",
)

conn = get_connection()

recipe_id = st.session_state.get("selected_recipe_id")
recipe = get_recipe(conn, recipe_id) if recipe_id else None

if not recipe:
    st.warning("No recipe selected.")
    if st.button("← Back to Recipes"):
        st.switch_page("pages/1_Recipes.py")
    st.stop()

steps = split_instructions_into_steps(recipe.instructions)

# Reset to the first step whenever Cook Mode is opened for a different
# recipe; Next/Back reruns this same page for the same recipe, so the
# reset condition won't fire on those.
if st.session_state.get("cook_mode_recipe_id") != recipe.id:
    st.session_state["cook_mode_step_index"] = 0
    st.session_state["cook_mode_recipe_id"] = recipe.id

st.caption(recipe.name)

if photos.photo_exists(recipe.photo_path):
    st.image(str(photos.resolve_photo_path(recipe.photo_path)), width=150, caption=recipe.name)

if not steps:
    st.info("No instructions to cook from yet.")
else:
    step_index = st.session_state["cook_mode_step_index"]
    step_index = max(0, min(step_index, len(steps) - 1))

    st.caption(f"Step {step_index + 1} of {len(steps)}")
    st.markdown(f"# {steps[step_index]}")

    col1, col2 = st.columns(2)
    if col1.button("← Back", disabled=step_index == 0, use_container_width=True):
        st.session_state["cook_mode_step_index"] = step_index - 1
        st.rerun()
    if col2.button(
        "Next →", disabled=step_index == len(steps) - 1, use_container_width=True
    ):
        st.session_state["cook_mode_step_index"] = step_index + 1
        st.rerun()

with st.expander("Ingredients"):
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

if st.button("Exit Cook Mode"):
    st.switch_page("pages/3_Recipe_Detail.py")
