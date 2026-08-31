"""
Milestone 3 tests: weekly calendar service functions (services/calendar.py).
"""

import datetime as dt

from models import DAYS_OF_WEEK
from services.calendar import build_default_week_calendar


def test_build_default_week_calendar_returns_all_seven_days_in_order():
    calendar = build_default_week_calendar()
    assert tuple(day.day_of_week for day in calendar) == DAYS_OF_WEEK


def test_build_default_week_calendar_defaults_to_not_busy():
    calendar = build_default_week_calendar()
    assert all(day.is_busy is False for day in calendar)


def test_build_default_week_calendar_defaults_dinner_ready_time_to_6pm():
    calendar = build_default_week_calendar()
    assert all(day.dinner_ready_time == dt.time(18, 0) for day in calendar)


def test_build_default_week_calendar_returns_independent_objects_each_call():
    first = build_default_week_calendar()
    second = build_default_week_calendar()
    first[0].is_busy = True
    assert second[0].is_busy is False
