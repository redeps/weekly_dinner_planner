"""
Tests for services/ingredient_canonicalization.py.

Uses the real, messy raw ingredient-name strings found in the dev DB
during investigation (BBC Good Food-style URL imports) rather than
synthetic clean examples, since that's what the real coverage numbers in
docs/DECISIONS.md were measured against and what this module actually
has to cope with day to day.
"""

from services.ingredient_canonicalization import canonicalize_ingredient_name


# --- noise-word/phrase stripping merges real variant phrasings ---


def test_garlic_variants_share_one_canonical_name():
    variants = [
        "garlic clove finely grated",
        "garlic cloves crushed",
        "garlic cloves finely chopped",
        "of  garlic",
    ]
    canon = {canonicalize_ingredient_name(v) for v in variants}
    assert canon == {"garlic"}


def test_onion_variants_share_one_canonical_name():
    variants = [
        "large onion chopped",
        "onion finely chopped",
        "onion sliced",
        "onion thinly sliced",
    ]
    canon = {canonicalize_ingredient_name(v) for v in variants}
    assert canon == {"onion"}


def test_parmesan_variants_share_one_canonical_name():
    variants = [
        "freshly grated parmesan",
        "parmesan (or vegetarian alternative), grated, plus extra to serve",
        "parmesan or Grana Padano, freshly grated",
    ]
    canon = {canonicalize_ingredient_name(v) for v in variants}
    assert canon == {"parmesan"}


def test_creme_fraiche_variants_share_one_canonical_name():
    assert canonicalize_ingredient_name("/5oz crème fraîche") == canonicalize_ingredient_name(
        "crème fraîche"
    )


# --- Unicode-fraction leading-junk fix ---


def test_unicode_fraction_leading_quantity_is_stripped():
    """Real case found during investigation: the ASCII-only digit class
    originally missed '½', leaving 'fl oz beef stock' instead of 'beef
    stock' -- confirmed fixed against the exact real strings."""
    assert canonicalize_ingredient_name("/3½fl oz beef stock") == "beef stock"
    assert canonicalize_ingredient_name("beef stock") == "beef stock"


def test_multi_part_leading_quantity_is_fully_stripped():
    """Real case: '/1lb 2oz fillet steak sliced' has TWO leading
    quantity segments ('1lb' and '2oz') -- both must be consumed, not
    just the first, or 'oz fillet steak' leaks through."""
    assert canonicalize_ingredient_name("/1lb 2oz fillet steak sliced") == "fillet steak"


def test_other_vulgar_fractions_are_recognized():
    assert canonicalize_ingredient_name("¾ cup rice") == canonicalize_ingredient_name(
        "cup rice"
    )


# --- confirmed non-over-merge: distinct products stay distinct ---


def test_cherry_tomatoes_does_not_merge_with_canned_tomatoes():
    assert canonicalize_ingredient_name("cherry tomatoes halved") != canonicalize_ingredient_name(
        "can chopped tomatoes"
    )


def test_tomato_puree_does_not_merge_with_tomatoes():
    puree = canonicalize_ingredient_name("tomato purée")
    canned = canonicalize_ingredient_name("can chopped tomatoes")
    cherry = canonicalize_ingredient_name("cherry tomatoes halved")
    assert len({puree, canned, cherry}) == 3


def test_different_oils_do_not_merge():
    """Olive oil, sunflower oil, and vegetable oil are different products
    a shopper buys separately -- noise-stripping must not generalize them
    down to a shared generic 'oil'."""
    olive = canonicalize_ingredient_name("olive oil")
    sunflower = canonicalize_ingredient_name("sunflower oil")
    vegetable = canonicalize_ingredient_name("vegetable oil")
    assert len({olive, sunflower, vegetable}) == 3


# --- honest limitations, confirmed rather than papered over ---


def test_novel_phrasing_with_no_shared_token_does_not_merge():
    """'thai basil' and 'basil leaves' are both basil but share no
    surviving token after stripping -- a known, accepted limitation."""
    assert canonicalize_ingredient_name("of thai basil") != canonicalize_ingredient_name(
        "large handful basil leaves torn"
    )


def test_singular_plural_does_not_merge():
    """No stemming is attempted -- 'carrot' and 'carrots' stay distinct."""
    assert canonicalize_ingredient_name("medium carrot grated") != canonicalize_ingredient_name(
        "-3 medium carrots chopped"
    )


# --- alias table ---


def test_alias_table_maps_known_synonym():
    assert canonicalize_ingredient_name("cilantro") == "coriander"


def test_alias_applies_after_noise_stripping():
    assert canonicalize_ingredient_name("fresh cilantro, chopped") == "coriander"


# --- basic behavior ---


def test_empty_input_returns_empty_string():
    assert canonicalize_ingredient_name("") == ""
    assert canonicalize_ingredient_name("   ") == ""


def test_all_noise_input_falls_back_to_original_rather_than_empty():
    # "of" and "fresh" are both noise words -- stripping both would leave
    # nothing; falls back to the plain lowercased/stripped input instead
    # of returning an empty canonical name.
    assert canonicalize_ingredient_name("of fresh") == "of fresh"


def test_plain_name_with_no_noise_is_unchanged():
    assert canonicalize_ingredient_name("Butter") == "butter"
