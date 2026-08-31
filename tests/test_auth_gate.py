"""
Milestone 13 tests: household passphrase gate (services/auth.py).

Verified via AppTest against the real page scripts, not by calling
require_password() directly — it's inherently coupled to Streamlit's
script-execution context (st.stop(), st.rerun(), st.session_state), the
same reason pages/*.py themselves are tested through AppTest rather than
via direct function calls.

The specific case this whole mechanism exists for — see
docs/DECISIONS.md — is that Streamlit multipage apps let a user deep-link
directly to any pages/*.py file, bypassing app.py entirely. Streamlit's
own private-app access control would have caught that automatically; this
in-app gate has to do it itself, so it's tested against direct page loads
here, not just app.py's entry point.
"""

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from services import auth

REPO = Path(__file__).parent.parent
HOME_PAGE = str(REPO / "app.py")
# A representative sample of pages/*.py, deliberately excluding app.py,
# for the "every page is gated when loaded directly" check.
SAMPLE_PAGES = [
    str(REPO / "pages" / "1_Recipes.py"),
    str(REPO / "pages" / "5_Week_Plan.py"),
    str(REPO / "pages" / "8_Cook_Mode.py"),
]

TEST_PASSWORD = "correct-horse-battery-staple"


def test_home_page_shows_gate_when_not_authenticated():
    with patch.object(auth, "_get_expected_password", return_value=TEST_PASSWORD):
        at = AppTest.from_file(HOME_PAGE).run()
    assert not at.exception
    assert any(w.label == "Household passphrase" for w in at.text_input)
    assert not any("Backup" in s.value for s in at.subheader)


def test_wrong_password_shows_error_and_stays_gated():
    with patch.object(auth, "_get_expected_password", return_value=TEST_PASSWORD):
        at = AppTest.from_file(HOME_PAGE).run()
        password_input = [w for w in at.text_input if w.label == "Household passphrase"][0]
        at = password_input.set_value("wrong-guess").run()
    assert not at.exception
    assert any("Incorrect passphrase" in e.value for e in at.error)
    assert not any("Backup" in s.value for s in at.subheader)


def test_correct_password_unlocks_the_page():
    with patch.object(auth, "_get_expected_password", return_value=TEST_PASSWORD):
        at = AppTest.from_file(HOME_PAGE).run()
        password_input = [w for w in at.text_input if w.label == "Household passphrase"][0]
        at = password_input.set_value(TEST_PASSWORD).run()
    assert not at.exception
    assert any("Backup" in s.value for s in at.subheader)


def test_authentication_persists_across_reruns_in_the_same_session():
    with patch.object(auth, "_get_expected_password", return_value=TEST_PASSWORD):
        at = AppTest.from_file(HOME_PAGE).run()
        password_input = [w for w in at.text_input if w.label == "Household passphrase"][0]
        at = password_input.set_value(TEST_PASSWORD).run()
        for _ in range(3):
            at = at.run()
            assert not at.exception
            assert not any(w.label == "Household passphrase" for w in at.text_input)


def test_missing_secret_fails_closed():
    """No HOUSEHOLD_PASSWORD configured must refuse access, not silently
    let everyone in."""
    with patch.object(auth, "_get_expected_password", return_value=None):
        at = AppTest.from_file(HOME_PAGE).run()
    assert not at.exception
    assert any("not configured" in e.value for e in at.error)
    assert not any(w.label == "Household passphrase" for w in at.text_input)


def test_every_sampled_page_is_gated_when_loaded_directly():
    """The specific case that matters: a page loaded directly (not routed
    through app.py) must still show the gate — proving the deep-link
    bypass this mechanism exists for is actually closed, not just
    app.py's entry point."""
    for page in SAMPLE_PAGES:
        with patch.object(auth, "_get_expected_password", return_value=TEST_PASSWORD):
            at = AppTest.from_file(page).run()
        assert not at.exception, f"{page} raised: {at.exception}"
        assert any(
            w.label == "Household passphrase" for w in at.text_input
        ), f"{page} did not show the passphrase gate when loaded directly"


def test_direct_page_load_with_correct_password_unlocks_it():
    """Complements the previous test: not just that a direct load is
    gated, but that entering the correct passphrase on that same direct
    load actually unlocks the page's real content."""
    with patch.object(auth, "_get_expected_password", return_value=TEST_PASSWORD):
        at = AppTest.from_file(str(REPO / "pages" / "1_Recipes.py")).run()
        password_input = [w for w in at.text_input if w.label == "Household passphrase"][0]
        at = password_input.set_value(TEST_PASSWORD).run()
    assert not at.exception
    assert at.title[0].value == "Recipes"
