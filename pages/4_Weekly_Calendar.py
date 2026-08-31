"""
Weekly Calendar Input screen — a 7-day busy toggle + dinner-ready time
form. See docs/PRODUCT_SPEC.md §7 and §15.

Not database-backed: the calendar is re-entered each time rather than
persisted per week — see docs/DECISIONS.md. Milestone 4 will carry these
values into `plan_days` when a week plan is generated.
"""

import streamlit as st

from models import DAYS_OF_WEEK, CalendarDay
from services.calendar import build_default_week_calendar

st.set_page_config(page_title="Weekly Calendar — Meal Planner", page_icon="🍽️")

st.title("Weekly Calendar")
st.caption(
    "Mark busy days and adjust dinner-ready times. This will be used when "
    "generating a week plan (coming in a later milestone)."
)

if "weekly_calendar" not in st.session_state:
    st.session_state["weekly_calendar"] = build_default_week_calendar()

if st.button("Reset to defaults"):
    st.session_state["weekly_calendar"] = build_default_week_calendar()
    st.rerun()

calendar_by_day = {day.day_of_week: day for day in st.session_state["weekly_calendar"]}

updated_days = []
for day_name in DAYS_OF_WEEK:
    day = calendar_by_day[day_name]
    cols = st.columns([2, 1, 2])
    cols[0].write(f"**{day_name.capitalize()}**")
    is_busy = cols[1].checkbox("Busy", value=day.is_busy, key=f"cal_busy_{day_name}")
    dinner_ready_time = cols[2].time_input(
        "Dinner ready", value=day.dinner_ready_time, key=f"cal_time_{day_name}"
    )
    updated_days.append(
        CalendarDay(day_of_week=day_name, is_busy=is_busy, dinner_ready_time=dinner_ready_time)
    )

st.session_state["weekly_calendar"] = updated_days
