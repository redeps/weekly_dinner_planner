"""
Weekly Calendar Input screen — a 7-day busy toggle + dinner-ready time
form, plus the global default household size, an optional per-day
household-size override for days you're hosting or cooking for more than
usual, an optional per-day direct assignment of a special-occasion
recipe, optional per-day side-dish/dessert attachments (Milestone 16
Phase 2), and the "Generate New Plan" action that carries all of the
above into a new week plan. See docs/PRODUCT_SPEC.md §7 and §15.

Not database-backed: the calendar is re-entered each time rather than
persisted per week — see docs/DECISIONS.md. `generate_week_plan()` carries
these values into `plan_days` (and, for side/dessert attachments,
`plan_day_dishes`) when a week plan is generated. The default household
size is the one exception that IS persisted (`app_settings`, see
services/settings.py) — it's a standing setting, not a per-week input.

Every gated (yes/no -> multiselect -> per-day widget) section on this page
computes its yes/no radio's `index=` and its multiselect's `default=` from
`st.session_state["weekly_calendar"]` (the durable list), never relying on
the radio/multiselect's own widget-level session state alone — navigating
to another page and back can silently drop that widget state, and without
a computed default the gate falls back to "No" and the section's own
rebuild (right after the last gated section, so the Generate button below
it sees fresh values) then overwrites still-correct values with None. The
busy/dinner-time inputs above were never affected, since they're rendered
unconditionally every run and already compute their `value=` from the
durable list. See docs/DECISIONS.md. The Side dishes and Dessert sections
share one helper (`_render_dish_attachment_section`) since they're
identical apart from the course filter and labels — each writes its own
entry (`side_recipe_ids`/`dessert_recipe_ids`) into that same rebuild,
independently of every other section's fields, so none of them can clobber
each other (the exact bug class the household-size override already hit
once — see docs/DECISIONS.md).

Generation itself lives here rather than on the Week Plan screen (moved
after Milestone 15) — this page is the single place all pre-generation
input is entered, so clicking Generate right after entering it needs no
page switch. Week Plan no longer offers a generate/regenerate action at
all — see docs/DECISIONS.md for why a second copy of this button there
was rejected rather than kept as a convenience.
"""

import datetime as dt

import streamlit as st

from database import get_connection
from models import DAYS_OF_WEEK, CalendarDay
from services.auth import require_password
from services.calendar import build_default_week_calendar
from services.email import add_recipient, list_recipients, remove_recipient
from services.plan_generation import generate_week_plan
from services.recipes import list_recipes
from services.settings import get_default_household_size, set_default_household_size

st.set_page_config(page_title="Weekly Calendar — Meal Planner", page_icon="🍽️")
require_password()


def _render_dish_attachment_section(
    *,
    conn,
    calendar_by_day: dict,
    course: str,
    attr_name: str,
    section_title: str,
    week_question: str,
    key_prefix: str,
) -> dict:
    """Week-gated (yes/no -> which day(s) -> per-day multiselect of
    matching-course recipes) attachment picker — shared by the Side
    dishes and Dessert sections below, since they're identical apart
    from the course filter and labels. Symmetric multi-select for both:
    a day can have several sides *or* several desserts, same reasoning
    (see docs/DECISIONS.md). Mirrors the household-size/special-occasion
    sections' computed-default pattern (module docstring) so navigating
    away and back doesn't drop a day's attachments. Hidden entirely if
    no active recipe of this course exists yet, same as the
    special-occasion section."""
    course_recipes = list_recipes(conn, course=course)
    if not course_recipes:
        return {}

    st.divider()
    st.subheader(section_title)

    days_with_attachment = [
        day_name for day_name in DAYS_OF_WEEK
        if getattr(calendar_by_day[day_name], attr_name)
    ]

    hosting_this_week = st.radio(
        week_question,
        ("No", "Yes"),
        index=1 if days_with_attachment else 0,
        key=f"{key_prefix}_this_week",
    )

    attached_by_day: dict = {}
    if hosting_this_week == "Yes":
        chosen_days = st.multiselect(
            "Which day(s)?",
            DAYS_OF_WEEK,
            default=days_with_attachment,
            format_func=lambda day_name: day_name.capitalize(),
            key=f"{key_prefix}_days",
        )
        recipe_names_by_id = {r.id: r.name for r in course_recipes}
        options = [r.id for r in course_recipes]
        for day_name in chosen_days:
            cols = st.columns([2, 2])
            cols[0].write(f"**{day_name.capitalize()}**")
            existing = [
                rid for rid in getattr(calendar_by_day[day_name], attr_name)
                if rid in recipe_names_by_id
            ]
            chosen_ids = cols[1].multiselect(
                "Recipes",
                options=options,
                default=existing,
                format_func=lambda rid: recipe_names_by_id[rid],
                key=f"{key_prefix}_{day_name}",
            )
            if chosen_ids:
                attached_by_day[day_name] = chosen_ids

    return attached_by_day


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

days_with_household_override = [
    day_name for day_name in DAYS_OF_WEEK
    if calendar_by_day[day_name].household_size_override is not None
]

hosting_this_week = st.radio(
    "Are there any days this week you're hosting or cooking for more than "
    "your normal household?",
    ("No", "Yes"),
    index=1 if days_with_household_override else 0,
    key="hosting_extra_this_week",
)

household_override_by_day = {}
if hosting_this_week == "Yes":
    override_days = st.multiselect(
        "Which day(s)?",
        DAYS_OF_WEEK,
        default=days_with_household_override,
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

special_occasion_recipes = list_recipes(conn, special_occasion_only=True)

assigned_recipe_by_day = {}
if special_occasion_recipes:
    st.divider()
    st.subheader("Special-occasion recipes")

    days_with_assignment = [
        day_name for day_name in DAYS_OF_WEEK
        if calendar_by_day[day_name].assigned_recipe_id is not None
    ]

    hosting_special_this_week = st.radio(
        "Any holiday or special-occasion days this week?",
        ("No", "Yes"),
        index=1 if days_with_assignment else 0,
        key="special_occasion_this_week",
    )
    if hosting_special_this_week == "Yes":
        special_occasion_days = st.multiselect(
            "Which day(s)?",
            DAYS_OF_WEEK,
            default=days_with_assignment,
            format_func=lambda day_name: day_name.capitalize(),
            key="special_occasion_days",
        )
        recipe_names_by_id = {r.id: r.name for r in special_occasion_recipes}
        options = [None] + [r.id for r in special_occasion_recipes]
        for day_name in special_occasion_days:
            cols = st.columns([2, 2])
            cols[0].write(f"**{day_name.capitalize()}**")
            existing_assignment = calendar_by_day[day_name].assigned_recipe_id
            index = options.index(existing_assignment) if existing_assignment in options else 0
            chosen_recipe_id = cols[1].selectbox(
                "Recipe",
                options=options,
                format_func=lambda rid: "— choose a recipe —" if rid is None else recipe_names_by_id[rid],
                index=index,
                key=f"cal_special_occasion_{day_name}",
            )
            if chosen_recipe_id is not None:
                assigned_recipe_by_day[day_name] = chosen_recipe_id

side_dish_by_day = _render_dish_attachment_section(
    conn=conn,
    calendar_by_day=calendar_by_day,
    course="side",
    attr_name="side_recipe_ids",
    section_title="Side dishes",
    week_question="Any days this week you want to add a side dish?",
    key_prefix="side_dish",
)

dessert_by_day = _render_dish_attachment_section(
    conn=conn,
    calendar_by_day=calendar_by_day,
    course="dessert",
    attr_name="dessert_recipe_ids",
    section_title="Desserts",
    week_question="Any days this week you want to add a dessert?",
    key_prefix="dessert",
)

st.session_state["weekly_calendar"] = [
    CalendarDay(
        day_of_week=day_name,
        is_busy=busy_and_time_by_day[day_name][0],
        dinner_ready_time=busy_and_time_by_day[day_name][1],
        household_size_override=household_override_by_day.get(day_name),
        assigned_recipe_id=assigned_recipe_by_day.get(day_name),
        side_recipe_ids=side_dish_by_day.get(day_name, []),
        dessert_recipe_ids=dessert_by_day.get(day_name, []),
    )
    for day_name in DAYS_OF_WEEK
]

st.divider()
if st.button("Generate New Plan", type="primary"):
    today = dt.date.today()
    week_start = today - dt.timedelta(days=today.weekday())  # this week's Monday
    try:
        generate_week_plan(
            conn,
            week_start_date=week_start,
            calendar=st.session_state["weekly_calendar"],
        )
        st.switch_page("pages/5_Week_Plan.py")
    except ValueError as exc:
        st.error(str(exc))

st.divider()
st.subheader("Email recipients")
st.caption("The weekly plan can be emailed to this list from the Week Plan page.")

recipients = list_recipients(conn)
if recipients:
    for email in recipients:
        cols = st.columns([4, 1])
        cols[0].write(email)
        if cols[1].button("Remove", key=f"remove_recipient_{email}"):
            remove_recipient(conn, email)
            st.rerun()
else:
    st.caption("_No recipients added yet._")

new_recipient_email = st.text_input("Add an email address", key="new_recipient_email")
if st.button("Add recipient"):
    try:
        add_recipient(conn, new_recipient_email)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
