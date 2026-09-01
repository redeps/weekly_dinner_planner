"""
Meal Planner — Streamlit entry point (Home screen).

The full plan-at-a-glance view described in docs/PRODUCT_SPEC.md §15
(7 days, one line each) isn't built yet — no roadmap milestone has
explicitly called for it on Home so far. For now Home just confirms the
app is alive and links into the other screens.
"""

import datetime as dt

import streamlit as st

from database import export_database_bytes, get_connection
from services.auth import require_password
from services.recipes import seed_quick_fallback_recipes

st.set_page_config(page_title="Meal Planner", page_icon="🍽️")
require_password()


def main() -> None:
    st.title("🍽️ Meal Planner")
    st.caption("Milestone 12 — Polish")

    try:
        conn = get_connection()
        seed_quick_fallback_recipes(conn)
    except Exception as exc:  # noqa: BLE001 — surfaced directly to the user
        st.error(f"Database connection failed: {exc}")
        return

    if st.button("+ Add Recipe", type="primary", use_container_width=True):
        st.session_state.pop("edit_recipe_id", None)
        st.switch_page("pages/2_Add_Edit_Recipe.py")

    st.write(
        "Recipes, the weekly calendar, plan generation, the grocery list, "
        "cook history, and Cook Mode are all up and running — see "
        "`docs/ROADMAP.md` for what's next."
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

    st.subheader("Backup")
    st.caption(
        "Download a snapshot of your recipes, plans, and cook history. "
        "Recipe photos aren't included — back up the `photos/` folder "
        "separately if you want those too."
    )
    st.download_button(
        "Download Backup (.zip)",
        data=export_database_bytes(),
        file_name=f"meal_planner_backup_{dt.date.today().isoformat()}.zip",
        mime="application/zip",
    )


if __name__ == "__main__":
    main()
