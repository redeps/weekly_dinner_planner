"""
Deterministic bilingual categorization (services/categorization.py) —
tried before any AI call, see docs/DECISIONS.md. Pure function, no model,
no network. Coverage against real sample recipes is measured and reported
separately (not by this file) — these tests cover the matching logic
itself, including the specific substring collisions found while building
the keyword lists (e.g. "mince" inside "minced", "corn" inside
"cornstarch", "fisk" inside "fiskekraft").
"""

from services import categorization


def test_returns_none_for_blank_name():
    assert categorization.suggest_category("") is None
    assert categorization.suggest_category("   ") is None


def test_english_common_ingredients():
    assert categorization.suggest_category("chicken thighs") == "meat"
    assert categorization.suggest_category("onion, chopped") == "produce"
    assert categorization.suggest_category("cheddar cheese") == "dairy"
    assert categorization.suggest_category("olive oil") == "pantry"
    assert categorization.suggest_category("frozen peas") == "frozen"


def test_norwegian_common_ingredients():
    assert categorization.suggest_category("kylling") == "meat"
    assert categorization.suggest_category("hvitløk") == "produce"
    assert categorization.suggest_category("ost") == "dairy"
    assert categorization.suggest_category("olivenolje") == "pantry"
    assert categorization.suggest_category("frosne erter") == "frozen"


def test_returns_none_for_unmatched_ingredient():
    assert categorization.suggest_category("galangal") is None
    assert categorization.suggest_category("star anise") is None


def test_longest_match_wins_over_shorter_collision():
    """"minced" contains "mince", "cornstarch" contains "corn", and
    "fiskekraft" (fish stock) contains both "fisk" (fish -> meat) and
    "kraft" (stock -> pantry) — the longer, more specific keyword must
    win each time, not whichever category happens to be checked first."""
    assert categorization.suggest_category("garlic, minced") == "produce"  # not meat
    assert categorization.suggest_category("cornstarch") == "pantry"  # not produce
    assert categorization.suggest_category("fiskekraft") == "pantry"  # not meat


def test_conjunction_and_does_not_falsely_match_norwegian_duck():
    assert categorization.suggest_category("salt and pepper") == "pantry"


def test_frozen_overrides_the_underlying_ingredient_category():
    assert categorization.suggest_category("frozen chicken breast") == "frozen"
    assert categorization.suggest_category("frossen laks") == "frozen"
