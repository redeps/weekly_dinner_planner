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

Milestone 16 Phase 4 — multi-dish switcher: when the entry recipe's day
has attached sides/desserts (`plan_day_dishes`), a switcher appears above
the steps ("Main: Roast · Side: Salad · Dessert: Crumble") so a day with
several dishes doesn't require leaving Cook Mode and re-entering per dish.
Not concatenated into one step list — real dishes are cooked in parallel,
not as one linear sequence (see docs/DECISIONS.md) — each dish keeps its
own independent step progress (`cook_mode_step_index_by_recipe`, keyed by
recipe id), so switching to check the dessert's steps and back doesn't
lose the main's place. A day with no attached dishes shows no switcher at
all — behaves exactly as before this phase.
"""

import streamlit as st

from database import get_connection
from services import photos
from services.auth import require_password
from services.cook_mode import split_instructions_into_steps
from services.ingredients import list_ingredients
from services.plan_generation import get_plan_day, list_dishes
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

entry_recipe_id = st.session_state.get("selected_recipe_id")
entry_recipe = get_recipe(conn, entry_recipe_id) if entry_recipe_id else None

if not entry_recipe:
    st.warning("No recipe selected.")
    if st.button("← Back to Recipes"):
        st.switch_page("pages/1_Recipes.py")
    st.stop()

# A stale or mismatched plan_day_id must not scale/offer switching for an
# unrelated recipe — only trust it when the entry recipe actually belongs
# to that day, as its main or one of its attached dishes (see
# docs/DECISIONS.md).
plan_day_id = st.session_state.get("selected_plan_day_id")
plan_day = get_plan_day(conn, plan_day_id) if plan_day_id else None
dishes = list_dishes(conn, plan_day.id) if plan_day is not None else []
day_recipe_ids = {d.id for d in dishes}
if plan_day is not None and plan_day.recipe_id is not None:
    day_recipe_ids.add(plan_day.recipe_id)
plan_day = plan_day if plan_day is not None and entry_recipe.id in day_recipe_ids else None
if plan_day is None:
    dishes = []

# Fresh visit detection: a different entry recipe or a different day
# means a clean slate for both which dish is being viewed and every
# dish's step progress. Switching dishes *within* the same visit (via the
# switcher below) deliberately does not go through this reset — that's
# the whole point of tracking progress per recipe id instead of one
# global step index (the pre-Phase-4 shape).
if (
    st.session_state.get("cook_mode_entry_recipe_id") != entry_recipe.id
    or st.session_state.get("cook_mode_plan_day_id") != plan_day_id
):
    st.session_state["cook_mode_entry_recipe_id"] = entry_recipe.id
    st.session_state["cook_mode_plan_day_id"] = plan_day_id
    st.session_state["cook_mode_active_recipe_id"] = entry_recipe.id
    st.session_state["cook_mode_step_index_by_recipe"] = {}

recipe = entry_recipe

# Switcher — only when this day actually has attached dishes; a plain
# main-only day renders nothing here, unchanged from before this phase.
if plan_day is not None and dishes:
    switcher_options = []
    if plan_day.recipe_id is not None:
        main_recipe = get_recipe(conn, plan_day.recipe_id)
        if main_recipe is not None:
            switcher_options.append(("Main", main_recipe))
    for dish in dishes:
        switcher_options.append((dish.course.capitalize(), dish))

    option_ids = [r.id for _, r in switcher_options]
    labels_by_id = {r.id: f"{label}: {r.name}" for label, r in switcher_options}
    active_id = st.session_state["cook_mode_active_recipe_id"]
    default_index = option_ids.index(active_id) if active_id in option_ids else 0

    chosen_id = st.selectbox(
        "Dish",
        options=option_ids,
        index=default_index,
        format_func=lambda rid: labels_by_id[rid],
        key="cook_mode_dish_switcher",
    )
    st.session_state["cook_mode_active_recipe_id"] = chosen_id
    recipe = next(r for _, r in switcher_options if r.id == chosen_id)

steps = split_instructions_into_steps(recipe.instructions)

st.caption(recipe.name)

if photos.photo_exists(recipe.photo_path):
    st.image(str(photos.resolve_photo_path(recipe.photo_path)), width=150, caption=recipe.name)

step_index_by_recipe = st.session_state["cook_mode_step_index_by_recipe"]

if not steps:
    st.info("No instructions to cook from yet.")
else:
    step_index = step_index_by_recipe.get(recipe.id, 0)
    step_index = max(0, min(step_index, len(steps) - 1))
    step_index_by_recipe[recipe.id] = step_index

    st.caption(f"Step {step_index + 1} of {len(steps)}")
    st.markdown(f"# {steps[step_index]}")

    col1, col2 = st.columns(2)
    if col1.button("← Back", disabled=step_index == 0, use_container_width=True):
        step_index_by_recipe[recipe.id] = step_index - 1
        st.rerun()
    if col2.button(
        "Next →", disabled=step_index == len(steps) - 1, use_container_width=True
    ):
        step_index_by_recipe[recipe.id] = step_index + 1
        st.rerun()

# The currently-displayed recipe (main or an attached dish) is day-scoped
# for scaling purposes whenever it genuinely belongs to this plan_day —
# an attached dish scales exactly like the main, same household
# size/override (see docs/DECISIONS.md).
day_scoped = plan_day is not None and recipe.id in day_recipe_ids

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
