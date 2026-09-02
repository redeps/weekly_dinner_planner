"""
Recipe Detail screen — full recipe view, edit and deactivate actions. See
docs/PRODUCT_SPEC.md §15.

The optional "Suggest Shortcuts" action (AI Assist,
docs/AGENT_INSTRUCTIONS.md §6) just doesn't appear when Ollama isn't
reachable — everything else on this screen works identically either way.

Household-size scaling (Milestone 14) / special-occasion exemption
(docs/DECISIONS.md): reached with day context — `selected_plan_day_id`
in session state, set by Week Plan's View/Cook actions, pointing at
*this* recipe — shows scaled ingredient amounts via the same
`effective_ingredient_quantity()` helper Cook Mode and the grocery list
use; reached via generic browsing (no day context, or a stale/mismatched
one) shows the recipe's own original amounts, unscaled.
"""

import streamlit as st

from database import get_connection
from services import ai_assist, photos
from services.auth import require_password
from services.ingredients import list_ingredients
from services.plan_generation import get_plan_day
from services.recipes import deactivate_recipe, get_recipe
from services.settings import (
    effective_household_size,
    effective_ingredient_quantity,
    get_default_household_size,
)

st.set_page_config(page_title="Recipe Detail — Meal Planner", page_icon="🍽️")
require_password()

conn = get_connection()

recipe_id = st.session_state.get("selected_recipe_id")
recipe = get_recipe(conn, recipe_id) if recipe_id else None

if not recipe:
    st.warning("No recipe selected.")
    if st.button("← Back to Recipes"):
        st.switch_page("pages/1_Recipes.py")
    st.stop()

photo_error = st.session_state.pop("photo_error_message", None)
if photo_error:
    st.warning(photo_error)

st.title(recipe.name)

if photos.photo_exists(recipe.photo_path):
    st.image(str(photos.resolve_photo_path(recipe.photo_path)), width=300, caption=recipe.name)

badges = f"{recipe.cook_time_minutes} min · {'⭐' * recipe.family_enjoyment} · {recipe.seasonality}"
if recipe.is_quick_fallback:
    badges += " · ⚡ quick fallback"
if recipe.is_special_occasion:
    badges += " · 🎉 special occasion"
st.caption(badges)

if st.button("▶ Start Cooking", type="primary"):
    st.session_state["selected_recipe_id"] = recipe.id
    st.switch_page("pages/8_Cook_Mode.py")

st.write(f"**Servings:** {recipe.servings}")

# A stale or mismatched plan_day_id (e.g. left over from viewing a
# different day's recipe) must not scale this recipe — only trust it when
# it actually points at the recipe being shown right now.
plan_day_id = st.session_state.get("selected_plan_day_id")
plan_day = get_plan_day(conn, plan_day_id) if plan_day_id else None
day_scoped = plan_day is not None and plan_day.recipe_id == recipe.id

st.subheader("Ingredients")
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
        st.write(f"- {line}")

st.subheader("Instructions")
st.write(recipe.instructions or "_No instructions yet._")

st.subheader("Notes")
st.write(recipe.notes or "_No notes._")

if ai_assist.is_available():
    if st.button("🤖 Suggest Shortcuts"):
        st.session_state["shortcut_suggestion"] = ai_assist.suggest_shortcuts(recipe)
        st.session_state["shortcut_suggestion_for"] = recipe.id
    if st.session_state.get("shortcut_suggestion_for") == recipe.id:
        suggestion = st.session_state["shortcut_suggestion"]
        if suggestion:
            st.info(suggestion)
        else:
            st.caption("No shortcut suggestions right now.")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Edit"):
        st.session_state["edit_recipe_id"] = recipe.id
        st.switch_page("pages/2_Add_Edit_Recipe.py")
with col2:
    if st.button("Deactivate"):
        st.session_state["confirm_deactivate_id"] = recipe.id
with col3:
    if st.button("← Back to Recipes"):
        st.switch_page("pages/1_Recipes.py")

if st.session_state.get("confirm_deactivate_id") == recipe.id:
    st.warning(
        f"Deactivate **{recipe.name}**? It will stop appearing in browsing, "
        "plan generation, and swaps. This is reversible in the database "
        "(a soft-delete, not a permanent one), but there's no restore "
        "button in the UI yet."
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Yes, deactivate", type="primary"):
        deactivate_recipe(conn, recipe.id)
        st.session_state.pop("selected_recipe_id", None)
        st.session_state.pop("confirm_deactivate_id", None)
        st.switch_page("pages/1_Recipes.py")
    if cancel_col.button("Cancel"):
        st.session_state.pop("confirm_deactivate_id", None)
        st.rerun()
