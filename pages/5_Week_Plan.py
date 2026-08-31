"""
Week Plan screen — 7 days, each clickable into its recipe, with a swap
action per day. See docs/PRODUCT_SPEC.md §14 and §10.
"""

import datetime as dt

import streamlit as st

from database import get_connection
from models import DAYS_OF_WEEK
from services.calendar import build_default_week_calendar
from services.plan_generation import (
    generate_week_plan,
    get_latest_week_plan,
    list_plan_days,
    swap_day_recipe,
)
from services.recipes import get_recipe

st.set_page_config(page_title="Week Plan — Meal Planner", page_icon="🍽️")

conn = get_connection()

st.title("Week Plan")

if "weekly_calendar" not in st.session_state:
    st.session_state["weekly_calendar"] = build_default_week_calendar()

week_plan = get_latest_week_plan(conn)

if st.button("Generate New Plan", type="primary"):
    today = dt.date.today()
    week_start = today - dt.timedelta(days=today.weekday())  # this week's Monday
    try:
        generate_week_plan(
            conn,
            week_start_date=week_start,
            calendar=st.session_state["weekly_calendar"],
        )
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

if not week_plan:
    st.info(
        "No week plan yet. Add some recipes and click **Generate New Plan** "
        "to create one."
    )
    st.stop()

st.caption(f"Week of {week_plan.week_start_date}")

for plan_day in list_plan_days(conn, week_plan.id):
    recipe = get_recipe(conn, plan_day.recipe_id) if plan_day.recipe_id else None
    with st.container(border=True):
        cols = st.columns([1, 3, 1, 1])
        cols[0].write(f"**{plan_day.day_of_week.capitalize()}**")
        cols[0].caption(plan_day.date)
        if recipe:
            label = recipe.name
            if plan_day.is_busy:
                label += " · busy day"
            cols[1].write(label)
            cols[1].caption(
                f"{recipe.cook_time_minutes} min · dinner ready {plan_day.dinner_ready_time}"
            )
            if cols[2].button("View", key=f"view_day_{plan_day.id}"):
                st.session_state["selected_recipe_id"] = recipe.id
                st.switch_page("pages/3_Recipe_Detail.py")
            if cols[3].button("Swap", key=f"swap_day_{plan_day.id}"):
                try:
                    swap_day_recipe(conn, plan_day.id)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        else:
            cols[1].write("_No recipe assigned._")
