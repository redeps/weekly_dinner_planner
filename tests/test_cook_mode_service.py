"""
Milestone 7 tests: Cook Mode step-splitting (services/cook_mode.py).
"""

from services.cook_mode import split_instructions_into_steps


def test_splits_multiline_instructions_by_line():
    instructions = "Preheat oven to 200C.\nChop the onions.\nBake for 20 minutes."
    assert split_instructions_into_steps(instructions) == [
        "Preheat oven to 200C.",
        "Chop the onions.",
        "Bake for 20 minutes.",
    ]


def test_strips_whitespace_from_each_line():
    instructions = "  Preheat oven.  \n\tChop onions.\t\n  Bake.  "
    assert split_instructions_into_steps(instructions) == [
        "Preheat oven.",
        "Chop onions.",
        "Bake.",
    ]


def test_skips_blank_lines():
    instructions = "Step one.\n\n\nStep two.\n   \nStep three."
    assert split_instructions_into_steps(instructions) == [
        "Step one.",
        "Step two.",
        "Step three.",
    ]


def test_returns_empty_list_for_none():
    assert split_instructions_into_steps(None) == []


def test_returns_empty_list_for_empty_string():
    assert split_instructions_into_steps("") == []


def test_returns_empty_list_for_whitespace_only():
    assert split_instructions_into_steps("   \n  \n\t") == []


def test_single_line_with_no_breaks_returns_one_step():
    assert split_instructions_into_steps("Order takeout.") == ["Order takeout."]


def test_handles_windows_style_line_endings():
    instructions = "Step one.\r\nStep two.\r\nStep three."
    assert split_instructions_into_steps(instructions) == [
        "Step one.",
        "Step two.",
        "Step three.",
    ]
