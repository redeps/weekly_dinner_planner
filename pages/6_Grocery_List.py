"""
Grocery List screen — a read-only, generated, grouped-by-category table
for the current week plan. See docs/PRODUCT_SPEC.md §11.

Nothing here is persisted: this is recomputed from the live plan_days +
plan_day_dishes + recipe_ingredients on every render (Milestone 16 Phase
3 — each day's main *and* its attached sides/desserts), so it regenerates
automatically when a day is swapped or an attachment changes — no
separate refresh step needed. No check-off state or shopping-mode UI, per
docs/DECISIONS.md.

Rendered as a table (Category / Ingredient / Quantity / Unit, one row per
canonical ingredient+unit combination), not a bulleted list — see
docs/DECISIONS.md. The same row data backs the "Download as Excel (.csv)"
button below it (services.grocery_list.grocery_list_table_rows() /
grocery_list_csv()) — one underlying structure, two presentations.
"""

import streamlit as st

from database import get_connection
from services.auth import require_password
from services.grocery_list import build_grocery_list, grocery_list_csv, grocery_list_table_rows
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
    rows = grocery_list_table_rows(grocery_list)
    st.dataframe(
        [
            {
                "Category": row.category,
                "Ingredient": row.ingredient,
                "Quantity": row.quantity,
                "Unit": row.unit,
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.download_button(
        "Download as Excel (.csv)",
        # utf-8-sig (a UTF-8 BOM) so Excel on Windows renders the "—"
        # placeholder correctly instead of mojibake — Excel's CSV import
        # otherwise assumes a legacy Windows codepage for a BOM-less file.
        data=grocery_list_csv(grocery_list).encode("utf-8-sig"),
        file_name=f"grocery-list-{week_plan.week_start_date}.csv",
        mime="text/csv",
    )
