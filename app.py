"""
Meal Planner — Streamlit entry point (Home screen).

Milestone 1: recipes exist now. The weekly plan-at-a-glance view described
in docs/PRODUCT_SPEC.md §14 arrives in Milestone 4 — for now Home just
confirms the app is alive and links into the Recipes screen.
"""

import streamlit as st

from database import get_connection
from services.recipes import seed_quick_fallback_recipes

st.set_page_config(page_title="Meal Planner", page_icon="🍽️")


def main() -> None:
    st.title("🍽️ Meal Planner")
    st.caption("Milestone 1 — Core Recipes")

    try:
        conn = get_connection()
        seed_quick_fallback_recipes(conn)
    except Exception as exc:  # noqa: BLE001 — surfaced directly to the user
        st.error(f"Database connection failed: {exc}")
        return

    st.write(
        "Recipes are up and running. Weekly plans and the grocery list will "
        "appear here as later milestones are completed — see "
        "`docs/ROADMAP.md`."
    )

    if st.button("Browse Recipes →"):
        st.switch_page("pages/1_Recipes.py")


if __name__ == "__main__":
    main()
