"""
Weekly calendar input business logic (Milestone 3).

Not database-backed yet — the calendar is re-entered each time rather than
persisted per week; see docs/DECISIONS.md. Milestone 4 carries these values
into `plan_days` when a week plan is generated.
"""

from models import DAYS_OF_WEEK, DEFAULT_DINNER_READY_TIME, CalendarDay


def build_default_week_calendar() -> list[CalendarDay]:
    """Return a fresh 7-day calendar: no busy days, dinner ready at the
    default time (6:00 PM) every day."""
    return [
        CalendarDay(
            day_of_week=day, is_busy=False, dinner_ready_time=DEFAULT_DINNER_READY_TIME
        )
        for day in DAYS_OF_WEEK
    ]
