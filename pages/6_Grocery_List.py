"""
Grocery List screen — a read-only, generated, grouped-by-category list for
the current week plan. See docs/PRODUCT_SPEC.md §11.

Nothing here is persisted: this is recomputed from the live plan_days +
recipe_ingredients on every render, so it regenerates automatically when a
day is swapped — no separate refresh step needed. No check-off state or
shopping-mode UI, per docs/DECISIONS.md.

Each GroceryItem is a canonical-name group (services/ingredient_
canonicalization.py) that may carry more than one GroceryUnitLine — a
group with only one line (the common case) renders as a single flat line
exactly as before this existed; a group with more than one (different
units, or a mix of quantified and unscaled lines) renders as a heading
with its lines indented underneath, instead of scattering them elsewhere
in the section. See docs/DECISIONS.md.
"""

import streamlit as st

from database import get_connection
from services.auth import require_password
from services.grocery_list import build_grocery_list
from services.plan_generation import get_latest_week_plan

st.set_page_config(page_title="Grocery List — Meal Planner", page_icon="🍽️")
require_password()

conn = get_connection()

st.title("Grocery List")

week_plan = get_latest_week_plan(conn)
if not week_plan:
    st.info("No week plan yet. Generate one from the Week Plan screen first.")
    st.stop()

st.caption(f"Week of {week_plan.week_start_date}")

grocery_list = build_grocery_list(conn, week_plan.id)


def _format_line(quantity, unit) -> str:
    amount = " ".join(
        part for part in ("" if quantity is None else f"{quantity:g}", unit or "") if part
    )
    if quantity is None:
        return "_(not scaled — no quantity on the recipe)_"
    return amount


if not grocery_list:
    st.write("_No ingredients needed this week._")
else:
    for category, items in grocery_list.items():
        st.subheader(category.capitalize())
        for item in items:
            if len(item.lines) == 1:
                line = item.lines[0]
                if line.quantity is None:
                    st.write(f"- {item.name} {_format_line(line.quantity, line.unit)}")
                else:
                    st.write(f"- {_format_line(line.quantity, line.unit)} {item.name}".strip())
            else:
                st.write(f"- **{item.name}**")
                for line in item.lines:
                    st.write(f"    - {_format_line(line.quantity, line.unit)}")
