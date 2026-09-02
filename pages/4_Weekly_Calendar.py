"""
Weekly Calendar Input screen — a 7-day busy toggle + dinner-ready time
form, plus the global default household size and an optional per-day
household-size override for days you're hosting or cooking for more than
usual. See docs/PRODUCT_SPEC.md §7 and §15.

Not database-backed: the calendar is re-entered each time rather than
persisted per week — see docs/DECISIONS.md. `generate_week_plan()` carries
these values into `plan_days` when a week plan is generated. The default
household size is the one exception that IS persisted (`app_settings`,
see services/settings.py) — it's a standing setting, not a per-week input.
"""

import streamlit as st

from database import get_connection
from models import DAYS_OF_WEEK, CalendarDay
from services.auth import require_password
from services.calendar import build_default_week_calendar
from services.settings import get_default_household_size, set_default_household_size

st.set_page_config(page_title="Weekly Calendar — Meal Planner", page_icon="🍽️")
require_password()

conn = get_connection()

st.title("Weekly Calendar")
st.caption(
    "Mark busy days and adjust dinner-ready times. This will be used when "
    "generating a week plan."
)

if "weekly_calendar" not in st.session_state:
    st.session_state["weekly_calendar"] = build_default_week_calendar()

if st.button("Reset to defaults"):
    st.session_state["weekly_calendar"] = build_default_week_calendar()
    st.rerun()

calendar_by_day = {day.day_of_week: day for day in st.session_state["weekly_calendar"]}

busy_and_time_by_day = {}
for day_name in DAYS_OF_WEEK:
    day = calendar_by_day[day_name]
    cols = st.columns([2, 1, 2])
    cols[0].write(f"**{day_name.capitalize()}**")
    is_busy = cols[1].checkbox("Busy", value=day.is_busy, key=f"cal_busy_{day_name}")
    dinner_ready_time = cols[2].time_input(
        "Dinner ready", value=day.dinner_ready_time, key=f"cal_time_{day_name}"
    )
    busy_and_time_by_day[day_name] = (is_busy, dinner_ready_time)

st.divider()
st.subheader("Household size")

default_household_size = get_default_household_size(conn)
new_default_size = st.number_input(
    "Normal household size (used to scale ingredient quantities in the grocery list)",
    min_value=1,
    step=1,
    value=default_household_size,
    key="default_household_size_input",
)
if int(new_default_size) != default_household_size:
    set_default_household_size(conn, int(new_default_size))
    st.rerun()

hosting_this_week = st.radio(
    "Are there any days this week you're hosting or cooking for more than "
    "your normal household?",
    ("No", "Yes"),
    key="hosting_extra_this_week",
)

household_override_by_day = {}
if hosting_this_week == "Yes":
    override_days = st.multiselect(
        "Which day(s)?",
        DAYS_OF_WEEK,
        format_func=lambda day_name: day_name.capitalize(),
        key="household_override_days",
    )
    for day_name in override_days:
        cols = st.columns([2, 2])
        cols[0].write(f"**{day_name.capitalize()}**")
        existing_override = calendar_by_day[day_name].household_size_override
        size = cols[1].number_input(
            "Household size",
            min_value=1,
            step=1,
            value=existing_override or default_household_size,
            key=f"cal_household_size_{day_name}",
        )
        household_override_by_day[day_name] = int(size)

st.session_state["weekly_calendar"] = [
    CalendarDay(
        day_of_week=day_name,
        is_busy=busy_and_time_by_day[day_name][0],
        dinner_ready_time=busy_and_time_by_day[day_name][1],
        household_size_override=household_override_by_day.get(day_name),
    )
    for day_name in DAYS_OF_WEEK
]
