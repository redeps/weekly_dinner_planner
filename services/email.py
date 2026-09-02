"""
Weekly plan email — a manually-triggered send to a small, household-
maintained recipient list (Milestone 15, docs/ROADMAP.md). See
docs/DECISIONS.md for the full design reasoning: `email_recipients` table
vs. JSON on `app_settings`, stdlib `smtplib` over a mail-API SDK, one
message per recipient rather than one shared `To`, and why this feature
reports per-recipient success/failure instead of following R2 sync's
always-swallow pattern or `PhotoBackupError`'s raise-on-specific-failure
pattern.

Content is never reformatted from scratch: `build_plan_email_body()` walks
the exact same `list_plan_days()` / `get_recipe()` calls
`pages/5_Week_Plan.py` already makes to render the page.
"""

import re
import smtplib
from email.message import EmailMessage

import psycopg
import streamlit as st

from services.plan_generation import list_plan_days
from services.recipes import get_recipe

# A light shape check, not RFC 5322 validation — matches this project's
# existing "good enough, not overengineered" validation elsewhere (e.g.
# services/ingredients.py's store_category check).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SmtpConnectionError(Exception):
    """Raised when the SMTP connection/login itself fails, or when no
    `[smtp]` secrets section is configured — before any per-recipient send
    is attempted. Distinct from a per-recipient send failure (see
    `send_weekly_plan_email`'s return value): a connection/auth failure is
    one failure shared by every recipient, not an individual one, so it's
    surfaced as a single error rather than attempted per address."""


# --- recipient CRUD ---


def list_recipients(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute("SELECT email FROM email_recipients ORDER BY email").fetchall()
    return [row[0] for row in rows]


def add_recipient(conn: psycopg.Connection, email: str) -> None:
    email = email.strip()
    if not _EMAIL_RE.match(email):
        raise ValueError(f"{email!r} doesn't look like a valid email address.")
    conn.execute(
        "INSERT INTO email_recipients (email) VALUES (%s) ON CONFLICT (email) DO NOTHING",
        (email,),
    )
    conn.commit()


def remove_recipient(conn: psycopg.Connection, email: str) -> None:
    conn.execute("DELETE FROM email_recipients WHERE email = %s", (email,))
    conn.commit()


# --- content ---


def build_plan_email_body(conn: psycopg.Connection, week_plan) -> str:
    """Plain-text body: one line per day (day, date, recipe, cook time) —
    not the full instructions. Reuses the same data pages/5_Week_Plan.py
    already fetches to render the page, not a separate query."""
    lines = [f"Week Plan -- week of {week_plan.week_start_date}", ""]
    for plan_day in list_plan_days(conn, week_plan.id):
        recipe = get_recipe(conn, plan_day.recipe_id) if plan_day.recipe_id else None
        day_label = f"{plan_day.day_of_week.capitalize()} ({plan_day.date})"
        if recipe:
            line = f"{day_label}: {recipe.name} -- {recipe.cook_time_minutes} min"
            if plan_day.is_busy:
                line += " -- busy day"
        else:
            line = f"{day_label}: No recipe assigned"
        lines.append(line)
    return "\n".join(lines)


# --- sending ---


def smtp_configured() -> bool:
    try:
        return bool(st.secrets.get("smtp"))
    except Exception:
        return False


def _smtp_connection() -> smtplib.SMTP:
    """A logged-in SMTP connection, built fresh per send. A separate,
    monkeypatchable function (mirroring services/photos.py's
    `_r2_client()`) so tests can substitute a fake connection instead of
    hitting a real mail server."""
    secrets = st.secrets["smtp"]
    server = smtplib.SMTP(secrets["host"], int(secrets["port"]), timeout=10)
    server.starttls()
    server.login(secrets["username"], secrets["app_password"])
    return server


def _from_address() -> str:
    """A separate, monkeypatchable accessor (same reasoning as
    `_smtp_connection()`) so tests never need to touch `st.secrets`
    directly."""
    return st.secrets["smtp"]["username"]


def send_weekly_plan_email(
    conn: psycopg.Connection, week_plan
) -> tuple[list[str], dict[str, str]]:
    """Send the week plan to every address in `email_recipients`, one
    message per recipient rather than one message with everyone in `To`
    — isolates a bad address from the rest of the list, and keeps the
    household's recipient addresses from being exposed to each other (see
    docs/DECISIONS.md).

    Returns `(sent, failed)`: `sent` is the list of addresses the send
    succeeded for; `failed` maps address -> error message for addresses
    that didn't. Raises `SmtpConnectionError` if SMTP isn't configured, or
    the connection/login itself fails, before attempting any per-address
    send — see that exception's docstring for why this is a distinct
    failure mode from a per-address one.
    """
    if not smtp_configured():
        raise SmtpConnectionError("Email sending isn't configured (no [smtp] secrets section).")

    recipients = list_recipients(conn)
    body = build_plan_email_body(conn, week_plan)
    subject = f"Week Plan -- week of {week_plan.week_start_date}"

    try:
        server = _smtp_connection()
        from_address = _from_address()
    except Exception as exc:
        raise SmtpConnectionError(str(exc)) from exc

    sent: list[str] = []
    failed: dict[str, str] = {}
    try:
        for address in recipients:
            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = from_address
            message["To"] = address
            message.set_content(body)
            try:
                server.send_message(message)
                sent.append(address)
            except Exception as exc:
                failed[address] = str(exc)
    finally:
        try:
            server.quit()
        except Exception:
            pass

    return sent, failed
