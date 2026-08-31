"""
Household passphrase gate. See docs/DECISIONS.md — Streamlit Community
Cloud's free tier allows only one private app, already used by the
household's other app, so this one deploys as a public app instead,
gated by a shared passphrase rather than Streamlit's private-app
mechanism.

Must be called at the very top of app.py and every file in pages/, right
after st.set_page_config() (which Streamlit requires to be the first
Streamlit call in a script). Streamlit multipage apps let a user
deep-link directly to any page, bypassing app.py entirely, so a gate
only in app.py protects nothing — every page needs its own call.
"""

import hmac
from typing import Optional

import streamlit as st


def _get_expected_password() -> Optional[str]:
    return st.secrets.get("HOUSEHOLD_PASSWORD")


def require_password() -> None:
    """Show a passphrase gate if this session hasn't authenticated yet.
    Returns immediately (no re-prompt) once authenticated. Otherwise
    st.stop()s the page so nothing else renders."""
    if st.session_state.get("authenticated"):
        return

    st.title("🍽️ Meal Planner")

    expected = _get_expected_password()
    if not expected:
        st.error("App not configured — the HOUSEHOLD_PASSWORD secret is missing.")
        st.stop()

    password = st.text_input("Household passphrase", type="password")
    if password:
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect passphrase.")
    st.stop()
