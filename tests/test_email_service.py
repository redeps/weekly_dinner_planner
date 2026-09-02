"""
Weekly plan email tests (services/email.py). SMTP is never actually
dialed — `_smtp_connection()` is monkeypatched to a fake connection
object, matching how services/photos.py's `_r2_client()` is swapped out
in tests/test_photos_service.py rather than hitting a real service.
"""

import datetime as dt
import random

import pytest

import database
from models import DAYS_OF_WEEK, CalendarDay
from services import email as email_service
from services import plan_generation as plan_service
from services import recipes as recipe_service


@pytest.fixture
def conn(tmp_path):
    connection = database.get_connection(identity=tmp_path)
    yield connection
    schema = database.schema_name_for(tmp_path)
    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def make_recipe(conn, **overrides):
    fields = dict(
        name="Test Recipe",
        cook_time_minutes=30,
        family_enjoyment=3,
        seasonality="all-season",
        servings=4,
    )
    fields.update(overrides)
    recipe_id = recipe_service.create_recipe(conn, **fields)
    return recipe_service.get_recipe(conn, recipe_id)


def make_week_plan(conn):
    make_recipe(conn, name="Chicken Fajitas", cook_time_minutes=25)
    calendar = [
        CalendarDay(day_of_week=day, is_busy=False, dinner_ready_time=dt.time(18, 0))
        for day in DAYS_OF_WEEK
    ]
    week_plan_id = plan_service.generate_week_plan(
        conn, week_start_date=dt.date(2026, 9, 7), calendar=calendar, rng=random.Random(0)
    )
    return plan_service.get_week_plan(conn, week_plan_id)


class FakeSmtpConnection:
    """Stands in for smtplib.SMTP: records every message sent, and can be
    configured to raise for specific recipient addresses."""

    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.sent_to = []
        self.quit_called = False

    def send_message(self, message):
        to_address = message["To"]
        if to_address in self.fail_for:
            raise Exception(f"simulated failure for {to_address}")
        self.sent_to.append(to_address)

    def quit(self):
        self.quit_called = True


# --- recipient CRUD ---


def test_add_recipient_stores_email(conn):
    email_service.add_recipient(conn, "alice@example.com")
    assert email_service.list_recipients(conn) == ["alice@example.com"]


def test_add_recipient_strips_whitespace(conn):
    email_service.add_recipient(conn, "  alice@example.com  ")
    assert email_service.list_recipients(conn) == ["alice@example.com"]


def test_add_recipient_rejects_invalid_shape(conn):
    with pytest.raises(ValueError):
        email_service.add_recipient(conn, "not-an-email")
    assert email_service.list_recipients(conn) == []


def test_add_recipient_ignores_duplicate(conn):
    email_service.add_recipient(conn, "alice@example.com")
    email_service.add_recipient(conn, "alice@example.com")
    assert email_service.list_recipients(conn) == ["alice@example.com"]


def test_list_recipients_returns_sorted(conn):
    email_service.add_recipient(conn, "zoe@example.com")
    email_service.add_recipient(conn, "alice@example.com")
    assert email_service.list_recipients(conn) == ["alice@example.com", "zoe@example.com"]


def test_remove_recipient_deletes_it(conn):
    email_service.add_recipient(conn, "alice@example.com")
    email_service.add_recipient(conn, "bob@example.com")
    email_service.remove_recipient(conn, "alice@example.com")
    assert email_service.list_recipients(conn) == ["bob@example.com"]


def test_remove_recipient_missing_address_is_a_no_op(conn):
    email_service.add_recipient(conn, "alice@example.com")
    email_service.remove_recipient(conn, "nobody@example.com")
    assert email_service.list_recipients(conn) == ["alice@example.com"]


# --- build_plan_email_body ---


def test_build_plan_email_body_includes_recipe_and_cook_time(conn):
    week_plan = make_week_plan(conn)
    body = email_service.build_plan_email_body(conn, week_plan)
    assert "Chicken Fajitas" in body
    assert "25 min" in body
    assert "Monday" in body
    assert str(week_plan.week_start_date) in body


def test_build_plan_email_body_marks_no_recipe_days(conn):
    # A week plan with only one recipe still fills every day (repeats
    # allowed when the pool is smaller than 7) -- to get an actual
    # unassigned day we'd need recipe_id set to NULL directly.
    week_plan = make_week_plan(conn)
    days = plan_service.list_plan_days(conn, week_plan.id)
    conn.execute("UPDATE plan_days SET recipe_id = NULL WHERE id = %s", (days[0].id,))
    conn.commit()
    body = email_service.build_plan_email_body(conn, week_plan)
    assert "No recipe assigned" in body


# --- smtp_configured ---


def test_smtp_configured_false_when_not_monkeypatched(conn):
    # This repo's real .streamlit/secrets.toml has no [smtp] section.
    assert email_service.smtp_configured() is False


# --- send_weekly_plan_email ---


def test_send_weekly_plan_email_raises_when_smtp_not_configured(conn, monkeypatch):
    monkeypatch.setattr(email_service, "smtp_configured", lambda: False)
    week_plan = make_week_plan(conn)
    email_service.add_recipient(conn, "alice@example.com")
    with pytest.raises(email_service.SmtpConnectionError):
        email_service.send_weekly_plan_email(conn, week_plan)


def test_send_weekly_plan_email_all_succeed(conn, monkeypatch):
    fake = FakeSmtpConnection()
    monkeypatch.setattr(email_service, "smtp_configured", lambda: True)
    monkeypatch.setattr(email_service, "_smtp_connection", lambda: fake)
    monkeypatch.setattr(email_service, "_from_address", lambda: "household@example.com")

    week_plan = make_week_plan(conn)
    email_service.add_recipient(conn, "alice@example.com")
    email_service.add_recipient(conn, "bob@example.com")

    sent, failed = email_service.send_weekly_plan_email(conn, week_plan)

    assert sorted(sent) == ["alice@example.com", "bob@example.com"]
    assert failed == {}
    assert fake.quit_called is True


def test_send_weekly_plan_email_reports_partial_failure(conn, monkeypatch):
    fake = FakeSmtpConnection(fail_for={"bob@example.com"})
    monkeypatch.setattr(email_service, "smtp_configured", lambda: True)
    monkeypatch.setattr(email_service, "_smtp_connection", lambda: fake)
    monkeypatch.setattr(email_service, "_from_address", lambda: "household@example.com")

    week_plan = make_week_plan(conn)
    email_service.add_recipient(conn, "alice@example.com")
    email_service.add_recipient(conn, "bob@example.com")

    sent, failed = email_service.send_weekly_plan_email(conn, week_plan)

    assert sent == ["alice@example.com"]
    assert "bob@example.com" in failed
    assert "simulated failure" in failed["bob@example.com"]
    assert fake.quit_called is True


def test_send_weekly_plan_email_connection_failure_short_circuits(conn, monkeypatch):
    """A connection/login failure must not attempt any per-recipient send
    at all -- it's a single failure shared by every recipient, not a
    per-address one (see SmtpConnectionError's docstring)."""

    def _raise_connection():
        raise ConnectionError("simulated connection failure")

    monkeypatch.setattr(email_service, "smtp_configured", lambda: True)
    monkeypatch.setattr(email_service, "_smtp_connection", _raise_connection)

    week_plan = make_week_plan(conn)
    email_service.add_recipient(conn, "alice@example.com")

    with pytest.raises(email_service.SmtpConnectionError):
        email_service.send_weekly_plan_email(conn, week_plan)
