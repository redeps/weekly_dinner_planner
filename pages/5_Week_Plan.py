"""
Week Plan screen — 7 days, each clickable into its recipe, with a swap
action per day. See docs/PRODUCT_SPEC.md §15 and §10.

Generating a new plan happens on the Weekly Calendar screen, not here —
see that page's docstring and docs/DECISIONS.md. This page only ever reads
the latest week plan and offers post-generation actions (swap, finalize,
email, cook).

The optional swap-intent hint (AI Assist, docs/AGENT_INSTRUCTIONS.md §6)
just doesn't appear when Ollama isn't reachable — Swap always works with
or without it.
"""

import streamlit as st

from database import get_connection
from models import DAYS_OF_WEEK
from services import ai_assist, photos
from services.auth import require_password
from services.cook_history import finalize_plan, has_been_cooked, mark_day_cooked
from services.email import SmtpConnectionError, list_recipients, send_weekly_plan_email
from services.plan_generation import get_latest_week_plan, list_plan_days, swap_day_recipe
from services.recipes import get_recipe

st.set_page_config(page_title="Week Plan — Meal Planner", page_icon="🍽️")
require_password()

conn = get_connection()

ai_available = ai_assist.is_available()

st.title("Week Plan")

week_plan = get_latest_week_plan(conn)

if not week_plan:
    st.info(
        "No week plan yet. Set up your week on the **Weekly Calendar** page "
        "and click **Generate New Plan** there to create one."
    )
    st.stop()

st.caption(f"Week of {week_plan.week_start_date}")

if st.button("Finalize Plan (mark all cooked)"):
    finalize_plan(conn, week_plan.id)
    st.rerun()

email_recipients = list_recipients(conn)
if email_recipients:
    if st.button("Send weekly plan by email"):
        try:
            sent, failed = send_weekly_plan_email(conn, week_plan)
        except SmtpConnectionError as exc:
            st.error(f"Couldn't send: {exc}")
        else:
            total = len(sent) + len(failed)
            if not failed:
                st.success(f"Sent to {len(sent)} recipient{'s' if len(sent) != 1 else ''}.")
            else:
                failure_detail = "; ".join(f"{addr} ({reason})" for addr, reason in failed.items())
                if sent:
                    st.warning(f"Sent to {len(sent)} of {total}. Failed: {failure_detail}")
                else:
                    st.error(f"Couldn't send to any recipient. Failed: {failure_detail}")
else:
    st.caption(
        "Add recipient email addresses on the Weekly Calendar page to enable "
        "emailing the plan."
    )

for plan_day in list_plan_days(conn, week_plan.id):
    recipe = get_recipe(conn, plan_day.recipe_id) if plan_day.recipe_id else None
    with st.container(border=True):
        # Each day is a compact, always-visible summary line with the
        # buttons tucked into a collapsed "Actions" expander — keeps 7
        # days scannable on a narrow/mobile screen instead of 7 rows of
        # 4-5 buttons each always expanded.
        cols = st.columns([1, 3])
        cols[0].write(f"**{plan_day.day_of_week.capitalize()}**")
        cols[0].caption(plan_day.date)
        if recipe:
            cooked = has_been_cooked(conn, plan_day.id)
            if photos.photo_exists(recipe.photo_path):
                cols[1].image(
                    str(photos.resolve_photo_path(recipe.photo_path)), width=60, caption=recipe.name
                )
            label = recipe.name
            if plan_day.is_busy:
                label += " · busy day"
            if cooked:
                label += " · ✓ Cooked"
            cols[1].write(label)
            cols[1].caption(
                f"{recipe.cook_time_minutes} min · dinner ready {plan_day.dinner_ready_time}"
            )

            with st.expander("Actions"):
                action_cols = st.columns(3)
                if action_cols[0].button(
                    "View", key=f"view_day_{plan_day.id}", use_container_width=True
                ):
                    st.session_state["selected_recipe_id"] = recipe.id
                    st.session_state["selected_plan_day_id"] = plan_day.id
                    st.switch_page("pages/3_Recipe_Detail.py")
                if action_cols[1].button(
                    "Swap", key=f"swap_day_{plan_day.id}", use_container_width=True
                ):
                    try:
                        intent = st.session_state.get(f"swap_intent_{plan_day.id}", "").strip()
                        candidate_filter = None
                        if ai_available and intent:
                            candidate_filter = lambda candidates, _i=intent: (
                                ai_assist.narrow_candidates_by_intent(candidates, _i)
                            )
                        swap_day_recipe(conn, plan_day.id, candidate_filter=candidate_filter)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                if action_cols[2].button(
                    "Cook", key=f"cook_day_{plan_day.id}", use_container_width=True
                ):
                    st.session_state["selected_recipe_id"] = recipe.id
                    st.session_state["selected_plan_day_id"] = plan_day.id
                    st.switch_page("pages/8_Cook_Mode.py")

                if not cooked:
                    if st.button(
                        "Mark Cooked", key=f"mark_cooked_{plan_day.id}", use_container_width=True
                    ):
                        mark_day_cooked(conn, plan_day.id)
                        st.rerun()

                if ai_available:
                    st.text_input(
                        "Swap intent (optional)",
                        key=f"swap_intent_{plan_day.id}",
                        placeholder="e.g. vegetarian, quicker, use up broccoli...",
                    )
        else:
            cols[1].write("_No recipe assigned._")
