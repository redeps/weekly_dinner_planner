"""
Grocery List screen — a read-only, generated, grouped-by-category list for
the current week plan. See docs/PRODUCT_SPEC.md §11.

Nothing here is persisted: this is recomputed from the live plan_days +
recipe_ingredients on every render, so it regenerates automatically when a
day is swapped — no separate refresh step needed. No check-off state or
shopping-mode UI, per docs/DECISIONS.md.
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

if not grocery_list:
    st.write("_No ingredients needed this week._")
else:
    for category, items in grocery_list.items():
        st.subheader(category.capitalize())
        for item in items:
            amount = " ".join(
                part
                for part in (
                    "" if item.quantity is None else f"{item.quantity:g}",
                    item.unit or "",
                )
                if part
            )
            line = f"{amount} {item.name}".strip() if amount else item.name
            st.write(f"- {line}")
