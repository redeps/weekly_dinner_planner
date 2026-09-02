"""
Cook Mode — a distraction-free, large-font, step-by-step view of a single
recipe's instructions, meant to be read at a glance while actually
cooking. See docs/PRODUCT_SPEC.md §12. Read-only: no editing happens here;
corrections go through the normal Edit Recipe form.

Steps are derived by splitting the recipe's existing `instructions` text
at render time — no new schema, see docs/DATA_MODEL.md and
services/cook_mode.py. Household-size scaling is never applied to this
instruction text (docs/PRODUCT_SPEC.md §11) — only to the separate
ingredients list below, the same way and via the same shared helper as
Recipe Detail and the grocery list; see docs/DECISIONS.md.
"""

import streamlit as st

from database import get_connection
from services import photos
from services.auth import require_password
from services.cook_mode import split_instructions_into_steps
from services.ingredients import list_ingredients
from services.plan_generation import get_plan_day
from services.recipes import get_recipe
from services.settings import (
    effective_household_size,
    effective_ingredient_quantity,
    get_default_household_size,
)

st.set_page_config(
    page_title="Cook Mode — Meal Planner",
    page_icon="🍽️",
    initial_sidebar_state="collapsed",
)
require_password()

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

# A stale or mismatched plan_day_id must not scale this recipe — only
# trust it when it actually points at the recipe being shown right now
# (see docs/DECISIONS.md).
plan_day_id = st.session_state.get("selected_plan_day_id")
plan_day = get_plan_day(conn, plan_day_id) if plan_day_id else None
day_scoped = plan_day is not None and plan_day.recipe_id == recipe.id

with st.expander("Ingredients"):
    if day_scoped:
        default_household_size = get_default_household_size(conn)
        if recipe.is_special_occasion and plan_day.household_size_override is None:
            st.caption(
                f"Special-occasion recipe — showing original amounts "
                f"(serves {recipe.servings})."
            )
        else:
            day_size = effective_household_size(plan_day.household_size_override, default_household_size)
            st.caption(f"Originally serves {recipe.servings}, scaled to {day_size}.")

    ingredients = list_ingredients(conn, recipe.id)
    if not ingredients:
        st.write("_No ingredients listed._")
    else:
        for ingredient in ingredients:
            if day_scoped:
                display_quantity = effective_ingredient_quantity(
                    ingredient.quantity,
                    recipe_servings=recipe.servings,
                    is_special_occasion=recipe.is_special_occasion,
                    household_size_override=plan_day.household_size_override,
                    default_household_size=default_household_size,
                )
            else:
                display_quantity = ingredient.quantity
            amount = " ".join(
                part
                for part in (
                    "" if display_quantity is None else f"{display_quantity:g}",
                    ingredient.unit or "",
                )
                if part
            )
            line = f"{amount} {ingredient.name}".strip() if amount else ingredient.name
            if display_quantity is None and ingredient.quantity is None:
                line += " _(not scaled — no quantity on the recipe)_"
            st.write(f"- {line}")

if st.button("Exit Cook Mode"):
    st.switch_page("pages/3_Recipe_Detail.py")
