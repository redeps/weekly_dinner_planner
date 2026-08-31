"""
Shared pytest fixtures.

`authenticated_apptest` is for any *new* UI test that drives a page via
AppTest and needs to get past services/auth.py's household passphrase
gate. Existing UI test files (test_cook_history_ui.py, test_polish_ui.py)
already set `at.session_state["authenticated"] = True` directly at each
call site — this fixture exists so new test files don't have to repeat
that by hand.
"""

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def authenticated_apptest():
    """Factory fixture: AppTest.from_file(path), pre-authenticated past
    services/auth.py's gate, run once. Usage:

        def test_something(authenticated_apptest):
            at = authenticated_apptest(str(REPO / "pages" / "1_Recipes.py"))
    """

    def _load(path: str) -> AppTest:
        at = AppTest.from_file(path)
        at.session_state["authenticated"] = True
        return at.run()

    return _load
