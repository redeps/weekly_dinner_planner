"""
Meal Planner — Streamlit entry point.

Milestone 0 (Foundation): this file just proves the app runs and can reach
the database. Screens for recipes, plans, calendar input, and the grocery
list are added in later milestones — see docs/ROADMAP.md.
"""

import streamlit as st

from database import get_connection

st.set_page_config(page_title="Meal Planner", page_icon="🍽️")


def main() -> None:
    st.title("🍽️ Meal Planner")
    st.caption("Foundation build — Milestone 0")

    st.write(
        "This is the project skeleton. Recipes, weekly plans, and the "
        "grocery list will appear here as milestones are completed — see "
        "`docs/ROADMAP.md`."
    )

    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        st.success("Database connection OK.")
    except Exception as exc:  # noqa: BLE001 — surfaced directly to the user
        st.error(f"Database connection failed: {exc}")


if __name__ == "__main__":
    main()
