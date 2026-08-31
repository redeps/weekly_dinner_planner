"""
Cook History screen — a simple "what have we cooked lately" view. See
docs/PRODUCT_SPEC.md §13. Read-only: history rows are only ever written by
Week Plan's Mark Cooked / Finalize Plan actions, never by this page.
"""

import streamlit as st

from database import get_connection
from services.cook_history import list_recent_cook_history

st.set_page_config(page_title="Cook History — Meal Planner", page_icon="🍽️")

conn = get_connection()

st.title("Cook History")
st.caption("What have we cooked lately?")

entries = list_recent_cook_history(conn)

if not entries:
    st.info(
        "Nothing recorded yet. Mark a day cooked from the Week Plan screen "
        "to start building history."
    )
else:
    for entry in entries:
        st.write(f"- **{entry.cooked_on}** — {entry.recipe_name}")
