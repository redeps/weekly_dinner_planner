"""
Milestone 7 tests: Cook Mode step-splitting (services/cook_mode.py).
"""

from services.cook_mode import SPLIT_THRESHOLD_CHARS, split_instructions_into_steps


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


# --- secondary split: dense steps from real imported recipes ---
# Regression tests against real recipe text sampled from the dev DB while
# investigating the Cook Mode step-density problem (see docs/DECISIONS.md
# — Cook Mode secondary split entry).


def test_splits_dense_step_at_sentence_boundaries_lasagne():
    step = (
        "Heat oven to 200C/180C fan/gas 6. To assemble the lasagne, ladle a "
        "little of the ragu sauce into the bottom of the roasting tin or "
        "casserole dish, spreading the sauce all over the base. Place 2 "
        "sheets of lasagne on top of the sauce overlapping to make it fit, "
        "then repeat with more sauce and another layer of pasta. Repeat "
        "with a further 2 layers of sauce and pasta, finishing with a "
        "layer of pasta."
    )
    assert len(step) > SPLIT_THRESHOLD_CHARS
    assert split_instructions_into_steps(step) == [
        "Heat oven to 200C/180C fan/gas 6.",
        "To assemble the lasagne, ladle a little of the ragu sauce into "
        "the bottom of the roasting tin or casserole dish, spreading the "
        "sauce all over the base.",
        "Place 2 sheets of lasagne on top of the sauce overlapping to "
        "make it fit, then repeat with more sauce and another layer of "
        "pasta.",
        "Repeat with a further 2 layers of sauce and pasta, finishing "
        "with a layer of pasta.",
    ]


def test_splits_dense_step_at_sentence_boundaries_thai_curry():
    step = (
        "To make the curry, heat the oil in a saucepan over a low heat. "
        "Add the green curry paste and stir until fragrant – you won't "
        "need all the paste. Increase the heat to medium and add in the "
        "chicken pieces, coating with the paste. When the chicken has "
        "browned, spoon in half the coconut milk, avoiding adding any of "
        "the water at the bottom of the tin – this will split the curry. "
        "Stir continuously for 10 mins or until the chicken is fully "
        "cooked and the sauce is simmering."
    )
    assert len(step) > SPLIT_THRESHOLD_CHARS
    assert split_instructions_into_steps(step) == [
        "To make the curry, heat the oil in a saucepan over a low heat. "
        "Add the green curry paste and stir until fragrant – you won't "
        "need all the paste.",
        "Increase the heat to medium and add in the chicken pieces, "
        "coating with the paste.",
        "When the chicken has browned, spoon in half the coconut milk, "
        "avoiding adding any of the water at the bottom of the tin – "
        "this will split the curry.",
        "Stir continuously for 10 mins or until the chicken is fully "
        "cooked and the sauce is simmering.",
    ]


def test_dense_step_does_not_false_split_on_oven_temperature_shorthand():
    """'180C/fan 160C/gas 4' has no periods, so it's not a false-split risk
    on its own — this guards against a naive length-only splitter (e.g. one
    that chops mid-clause) breaking that shorthand across two sub-steps."""
    step = (
        "Meanwhile, heat the oven to 180C/fan 160C/gas 4, then make the "
        "mash. Boil the 900g potato, cut into chunks, in salted water for "
        "10-15 mins until tender. Drain, then mash with 85g butter and 3 "
        "tbsp milk."
    )
    assert len(step) > SPLIT_THRESHOLD_CHARS
    result = split_instructions_into_steps(step)
    assert result == [
        "Meanwhile, heat the oven to 180C/fan 160C/gas 4, then make the "
        "mash. Boil the 900g potato, cut into chunks, in salted water "
        "for 10-15 mins until tender.",
        "Drain, then mash with 85g butter and 3 tbsp milk.",
    ]
    assert "180C/fan 160C/gas 4" in result[0]


# --- secondary split: abbreviation guard ---


def test_does_not_split_after_tbsp_abbreviation():
    step = (
        "Add 2 tbsp. Butter and stir well until fully melted, then season "
        "generously with salt and plenty of freshly ground black pepper "
        "to taste before removing the pan from the heat entirely."
    )
    assert len(step) > SPLIT_THRESHOLD_CHARS
    result = split_instructions_into_steps(step)
    assert len(result) == 1
    assert result[0] == step


def test_does_not_split_after_approx_abbreviation():
    step = (
        "Mix everything together thoroughly in a large bowl until fully "
        "combined and no dry patches remain. Chill for approx. 30 mins "
        "before serving to allow the flavours to develop properly."
    )
    assert len(step) > SPLIT_THRESHOLD_CHARS
    result = split_instructions_into_steps(step)
    assert result == [
        "Mix everything together thoroughly in a large bowl until fully "
        "combined and no dry patches remain.",
        "Chill for approx. 30 mins before serving to allow the flavours "
        "to develop properly.",
    ]


def test_splits_correctly_around_dr_abbreviation():
    step = (
        "Dr. Smith's original recipe calls for a generous pinch of "
        "saffron threads steeped in warm milk. Substitute ground "
        "turmeric if saffron is unavailable, though the flavour will "
        "differ noticeably from the original."
    )
    assert len(step) > SPLIT_THRESHOLD_CHARS
    result = split_instructions_into_steps(step)
    assert result == [
        "Dr. Smith's original recipe calls for a generous pinch of "
        "saffron threads steeped in warm milk.",
        "Substitute ground turmeric if saffron is unavailable, though "
        "the flavour will differ noticeably from the original.",
    ]


def test_short_step_under_threshold_is_not_split():
    step = "Preheat the oven to 200C and grease a large baking tray."
    assert len(step) <= SPLIT_THRESHOLD_CHARS
    assert split_instructions_into_steps(step) == [step]


def test_long_step_with_no_sentence_boundary_is_left_unsplit():
    step = "one two three four five six seven eight nine ten " * 5
    step = step.strip()
    assert len(step) > SPLIT_THRESHOLD_CHARS
    assert split_instructions_into_steps(step) == [step]
