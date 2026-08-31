"""
Meal Planner — Streamlit entry point (Home screen).

The full plan-at-a-glance view described in docs/PRODUCT_SPEC.md §15
(7 days, one line each) isn't built yet — no roadmap milestone has
explicitly called for it on Home so far. For now Home just confirms the
app is alive and links into the other screens.
"""

import streamlit as st

from database import get_connection
from services.recipes import seed_quick_fallback_recipes

st.set_page_config(page_title="Meal Planner", page_icon="🍽️")


def main() -> None:
    st.title("🍽️ Meal Planner")
    st.caption("Milestone 8 — Cook History")

    try:
        conn = get_connection()
        seed_quick_fallback_recipes(conn)
    except Exception as exc:  # noqa: BLE001 — surfaced directly to the user
        st.error(f"Database connection failed: {exc}")
        return

    st.write(
        "Recipes, the weekly calendar, plan generation, the grocery list, "
        "and cook history are all up and running — see `docs/ROADMAP.md` "
        "for what's next."
    )

    if st.button("Browse Recipes →"):
        st.switch_page("pages/1_Recipes.py")

    if st.button("Weekly Calendar →"):
        st.switch_page("pages/4_Weekly_Calendar.py")

    if st.button("Week Plan →"):
        st.switch_page("pages/5_Week_Plan.py")

    if st.button("Grocery List →"):
        st.switch_page("pages/6_Grocery_List.py")

    if st.button("Cook History →"):
        st.switch_page("pages/7_Cook_History.py")


if __name__ == "__main__":
    main()
