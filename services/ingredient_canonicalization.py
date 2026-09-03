"""
Deterministic, bilingual (English + Norwegian) ingredient-name
canonicalization, for grouping grocery-list lines that name the same
thing under different phrasing — e.g. "garlic cloves crushed", "garlic
clove finely grated", and "of  garlic" all collapse to `garlic`. Pure
function — no network, no model — same "no AI dependency" positioning as
services/categorization.py.

Deliberately a *separate* module and dictionary from
services/categorization.py, not a reuse of it. categorization.py's
keyword lookup is tuned for store-aisle breadth (a generic "tomato"
substring match is fine when the only question is "which aisle"), but
reusing it here for name identity was tested during investigation and
rejected: it wrongly collapsed "tomato purée" into the same group as
canned/fresh tomatoes, since all three contain the substring "tomato".
Grouping by name identity needs to be more conservative than grouping by
aisle — see docs/DECISIONS.md.

Real coverage, measured against the actual dev DB (105 ingredient rows /
90 distinct raw names, real BBC Good Food-style URL imports): noise-word
stripping alone (no alias-table entries needed for this corpus) collapses
19/90 (21.1%) of distinct raw names into 7 shared groups. This inverted
what was expected going in — the illustrative "Salt" / "Salt & Pepper"
framing suggested the alias/synonym table would carry the coverage, but
`recipeIngredient` lines are stored whole (see docs/DECISIONS.md,
Milestone 10), so real names are usually near-full prose ("garlic cloves
finely chopped"), and stripping the descriptive noise out of that prose
is what actually merges variants — a synonym table only helps when two
names use genuinely *different* words for the same thing, which this
particular (all-English, UK-vocabulary) sample didn't happen to surface.

The alias table below is intentionally sparse: a handful of anticipated
regional-English pairs plus a couple of Norwegian noise words, seeded
for the mechanism to exist, not because real usage has demonstrated a
need for them yet. Norwegian coverage as a whole is unvalidated — the
dev DB currently has zero Norwegian-sourced recipes to measure against;
see docs/DECISIONS.md. Grow both lists from real testing over time, the
same way categorization.py's own keyword dict grew.

What this can't solve (confirmed against real data, not hypothesized):
novel phrasing with no shared surviving token ("of thai basil" vs. "large
handful basil leaves torn" — both basil, no shared word survives
stripping); singular/plural ("carrot" vs. "carrots" — no stemming
attempted, since a stemmer risks wrongly collapsing unrelated short
words); and compound lines naming two ingredients in one string ("salt
and pepper") — not split, though stripping "and" as a noise word (see
below) does at least merge that phrasing with an already-compounded
"salt pepper" line, without ever merging either into plain "salt" alone.

Also deliberately not attempted here: leaked-field artifacts where
extraction put the wrong thing in the wrong column (a stray article word
like "a" landing in the `unit` field, or a spelled-out unit word like
"Grams" landing in the `name` field instead of `unit`). These are
extraction bugs, not name-phrasing variety — out of this module's scope
for the same reason quantity/unit extraction itself is out of scope; see
docs/DECISIONS.md.
"""

import re

# Vulgar-fraction characters common in UK recipe sites' quantity prefixes
# (e.g. "3½fl oz", "¾ cup") — added specifically because the ASCII-only
# digit class originally missed these, producing wrong leading-fragment
# strips ("/3½fl oz beef stock" -> "fl oz beef stock" instead of "beef
# stock"). See docs/DECISIONS.md.
_FRACTION_CHARS = "½¼¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞"

_UNIT_WORD = r"(?:lb|oz|g|kg|ml|l|fl\s*oz)"
_NUMBER_TOKEN = rf"(?:\d+(?:[./]\d+)?[{_FRACTION_CHARS}]?|[{_FRACTION_CHARS}])"
_QUANTITY_SEGMENT = rf"{_NUMBER_TOKEN}\s*{_UNIT_WORD}?"

# Leading fragments left over from source lines that weren't cleanly
# separated from quantity/unit text on import (recipeIngredient lines are
# stored whole — see module docstring). Repeats the quantity-segment
# match (`+`) so multi-part leading quantities like "1lb 2oz" are fully
# consumed, not just the first segment.
_LEADING_QUANTITY_RE = re.compile(
    rf"^[\-/x×]*\s*(?:{_QUANTITY_SEGMENT}\s*)+", re.IGNORECASE
)

_PAREN_RE = re.compile(r"\([^)]*\)")

# Descriptive/prep noise that doesn't change what's actually bought.
# English entries are validated against the real dev DB (see module
# docstring for the measured coverage). Norwegian entries are common,
# well-known prep words seeded for bilingual structure but NOT validated
# against real data — no Norwegian-sourced recipes exist yet to test
# against; see docs/DECISIONS.md.
_NOISE_PHRASES: tuple[str, ...] = (
    # English — validated
    "finely chopped", "roughly chopped", "finely sliced", "thinly sliced",
    "finely grated", "freshly grated", "cut into thin wedges",
    "cut into thin strips", "cut into chunks",
    "de-boned and cut into chunks", "boneless and skinless",
    "stems removed", "roughly torn", "such as arborio",
    "or vegetarian alternative", "to serve", "to taste", "plus extra",
    "see below", "zest only", "juiced", "at an angle",
    "peeled and thinly sliced", "skinned, de-boned", "to garnish",
    # Norwegian — unvalidated
    "finhakket", "grovhakket",
)

_NOISE_WORDS: frozenset[str] = frozenset({
    # English — validated
    "chopped", "crushed", "finely", "roughly", "grated", "sliced", "diced",
    "minced", "fresh", "freshly", "dried", "ground", "large", "small",
    "medium", "torn", "peeled", "boneless", "skinless", "thinly", "halved",
    "quartered", "de-boned", "deboned", "skinned", "bruised", "such", "as",
    "or", "and", "of", "clove", "cloves", "extra", "optional", "grana",
    "padano", "pack", "can", "cans", "handful", "bunch", "stalk", "stalks",
    "rashers", "stick", "divided",
    # Norwegian — unvalidated
    "hakket", "presset", "knust", "revet", "skivet", "fersk", "ferske",
    "tørket", "stor", "store", "liten", "lita", "små",
})

# Known different-word synonyms — deliberately sparse (see module
# docstring): applied only after noise-stripping, as an exact-match
# lookup on the already-normalized string, not a substring match (a
# substring alias lookup would reintroduce the over-merge risk that ruled
# out reusing categorization.py's dictionary). Canonical form on the
# right is an arbitrary pick, not a claim that it's the "correct" name.
_ALIASES: dict[str, str] = {
    # English regional pairs — anticipated, not yet observed in real data
    "cilantro": "coriander",
    "scallion": "green onion",
    "scallions": "green onion",
    "capsicum": "bell pepper",
    "rocket": "arugula",
    "aubergine": "eggplant",
    "courgette": "zucchini",
    # Norwegian — unvalidated
    "løk": "onion",
    "hvitløk": "garlic",
}

_WORD_RE = re.compile(r"[a-zà-ÿ']+")

# Unit spellings that are the exact same unit written differently — not a
# conversion table (tbsp and tsp stay permanently distinct; there's real
# conversion risk this project deliberately doesn't take on, see
# docs/DECISIONS.md). Canonical abbreviation on the right is arbitrary,
# not a claim it's the "correct" spelling.
_UNIT_SYNONYMS: dict[str, str] = {
    "tablespoon": "tbsp", "tablespoons": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp",
    "gram": "g", "grams": "g",
    "kilogram": "kg", "kilograms": "kg",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "pound": "lb", "pounds": "lb",
    "ounce": "oz", "ounces": "oz",
    "cups": "cup",
    "cloves": "clove",
}


def normalize_unit(raw_unit: str) -> str:
    """A canonical spelling for a unit string, so "tbsp" and
    "tablespoons" (the same unit written two ways) group together instead
    of showing as separate lines — never a conversion between genuinely
    different units (tbsp/tsp stay distinct). `None`/empty input passes
    through as `""`; callers already distinguish "no unit" from "has a
    unit" via truthiness, same as before this existed."""
    if not raw_unit or not raw_unit.strip():
        return ""
    normalized = raw_unit.strip().lower()
    return _UNIT_SYNONYMS.get(normalized, normalized)


def canonicalize_ingredient_name(raw_name: str) -> str:
    """A lowercase canonical identity for an ingredient name, for
    grouping grocery-list lines that name the same thing under different
    phrasing. Never raises; falls back to the plain lowercased/stripped
    input if normalization would otherwise leave nothing (e.g. a name
    that's entirely noise words)."""
    if not raw_name or not raw_name.strip():
        return ""
    original = raw_name.strip().lower()
    s = _LEADING_QUANTITY_RE.sub("", original).strip()
    s = _PAREN_RE.sub(" ", s).strip()
    for phrase in _NOISE_PHRASES:
        s = s.replace(phrase, " ")
    tokens = [t for t in _WORD_RE.findall(s) if t not in _NOISE_WORDS]
    canonical = " ".join(tokens).strip()
    if not canonical:
        canonical = original
    return _ALIASES.get(canonical, canonical)
