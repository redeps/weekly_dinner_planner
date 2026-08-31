"""
Milestone 10 tests: structured-data recipe import
(services/recipe_import.py).

Tests the JSON-LD extraction and field-mapping logic against two HTML
fixtures modeled on real-world schema.org/Recipe publishing patterns:
one with plain-string instructions and a text recipeYield (a simpler,
common site pattern), one with HowToStep instructions nested under
@graph and an integer recipeYield (a common recipe-plugin pattern).
"""

from unittest.mock import patch

from services import recipe_import

SIMPLE_RECIPE_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Simple Tomato Soup",
  "recipeYield": "4 servings",
  "cookTime": "PT30M",
  "recipeIngredient": [
    "2 cups chopped tomatoes",
    "1 onion, diced",
    "1 tbsp olive oil"
  ],
  "recipeInstructions": [
    "Heat the oil in a pot.",
    "Add the onion and cook until soft.",
    "Add the tomatoes and simmer for 20 minutes."
  ]
}
</script>
</head>
<body><h1>Simple Tomato Soup</h1></body>
</html>
"""

GRAPH_RECIPE_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "BreadcrumbList", "itemListElement": []},
    {
      "@type": "Recipe",
      "name": "Weeknight Chicken Curry",
      "recipeYield": 6,
      "totalTime": "PT1H15M",
      "recipeIngredient": [
        "500g chicken thighs",
        "1 can coconut milk"
      ],
      "recipeInstructions": [
        {"@type": "HowToStep", "text": "Marinate the chicken for 30 minutes."},
        {
          "@type": "HowToSection",
          "name": "Cook",
          "itemListElement": [
            {"@type": "HowToStep", "text": "Brown the chicken in a hot pan."},
            {"@type": "HowToStep", "text": "Add the coconut milk and simmer."}
          ]
        }
      ]
    }
  ]
}
</script>
</head>
<body><h1>Weeknight Chicken Curry</h1></body>
</html>
"""

NO_STRUCTURED_DATA_HTML = "<html><body><h1>Just a blog post</h1><p>No JSON-LD here.</p></body></html>"


# --- extract_json_ld_recipe ---


def test_extract_json_ld_recipe_from_simple_page():
    data = recipe_import.extract_json_ld_recipe(SIMPLE_RECIPE_HTML)
    assert data["name"] == "Simple Tomato Soup"


def test_extract_json_ld_recipe_from_graph_nested_page():
    data = recipe_import.extract_json_ld_recipe(GRAPH_RECIPE_HTML)
    assert data["name"] == "Weeknight Chicken Curry"


def test_extract_json_ld_recipe_returns_none_when_absent():
    assert recipe_import.extract_json_ld_recipe(NO_STRUCTURED_DATA_HTML) is None


def test_extract_json_ld_recipe_returns_none_for_empty_html():
    assert recipe_import.extract_json_ld_recipe("") is None


def test_extract_json_ld_recipe_tolerates_malformed_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert recipe_import.extract_json_ld_recipe(html) is None


# --- recipe_draft_from_json_ld: simple pattern ---


def test_recipe_draft_from_simple_json_ld():
    data = recipe_import.extract_json_ld_recipe(SIMPLE_RECIPE_HTML)
    draft = recipe_import.recipe_draft_from_json_ld(data)

    assert draft["name"] == "Simple Tomato Soup"
    assert draft["servings"] == 4
    assert draft["cook_time_minutes"] == 30
    assert draft["instructions"] == (
        "Heat the oil in a pot.\n"
        "Add the onion and cook until soft.\n"
        "Add the tomatoes and simmer for 20 minutes."
    )
    assert draft["ingredients"] == [
        {"name": "2 cups chopped tomatoes", "quantity": None, "unit": None},
        {"name": "1 onion, diced", "quantity": None, "unit": None},
        {"name": "1 tbsp olive oil", "quantity": None, "unit": None},
    ]


# --- recipe_draft_from_json_ld: HowToStep / @graph pattern ---


def test_recipe_draft_from_graph_json_ld_with_howto_steps():
    data = recipe_import.extract_json_ld_recipe(GRAPH_RECIPE_HTML)
    draft = recipe_import.recipe_draft_from_json_ld(data)

    assert draft["name"] == "Weeknight Chicken Curry"
    assert draft["servings"] == 6
    assert draft["cook_time_minutes"] == 75
    assert draft["instructions"] == (
        "Marinate the chicken for 30 minutes.\n"
        "Brown the chicken in a hot pan.\n"
        "Add the coconut milk and simmer."
    )
    assert draft["ingredients"] == [
        {"name": "500g chicken thighs", "quantity": None, "unit": None},
        {"name": "1 can coconut milk", "quantity": None, "unit": None},
    ]


def test_recipe_draft_from_json_ld_returns_none_without_name():
    assert recipe_import.recipe_draft_from_json_ld({"recipeYield": "4"}) is None


def test_recipe_draft_defaults_missing_servings_and_cook_time():
    draft = recipe_import.recipe_draft_from_json_ld({"name": "Mystery Dish"})
    assert draft["servings"] == 4
    assert draft["cook_time_minutes"] == 30
    assert draft["instructions"] is None
    assert draft["ingredients"] == []


# --- _parse_iso8601_duration_minutes ---


def test_parse_duration_hours_and_minutes():
    assert recipe_import._parse_iso8601_duration_minutes("PT1H15M") == 75


def test_parse_duration_minutes_only():
    assert recipe_import._parse_iso8601_duration_minutes("PT45M") == 45


def test_parse_duration_hours_only():
    assert recipe_import._parse_iso8601_duration_minutes("PT2H") == 120


def test_parse_duration_returns_none_for_garbage():
    assert recipe_import._parse_iso8601_duration_minutes("not a duration") is None
    assert recipe_import._parse_iso8601_duration_minutes(None) is None


# --- _coerce_servings ---


def test_coerce_servings_from_plain_int():
    assert recipe_import._coerce_servings(4) == 4


def test_coerce_servings_from_text():
    assert recipe_import._coerce_servings("4 servings") == 4


def test_coerce_servings_from_list():
    assert recipe_import._coerce_servings(["6 servings", "6-8 servings"]) == 6


def test_coerce_servings_returns_none_when_unparseable():
    assert recipe_import._coerce_servings("a lot") is None
    assert recipe_import._coerce_servings(None) is None


# --- parse_recipe_url (integration, with fetch mocked) ---


def test_parse_recipe_url_returns_draft_on_success():
    with patch.object(recipe_import, "fetch_html", return_value=SIMPLE_RECIPE_HTML):
        draft = recipe_import.parse_recipe_url("https://example.com/tomato-soup")
    assert draft["name"] == "Simple Tomato Soup"


def test_parse_recipe_url_returns_none_when_fetch_fails():
    with patch.object(recipe_import, "fetch_html", return_value=None):
        assert recipe_import.parse_recipe_url("https://example.com/unreachable") is None


def test_parse_recipe_url_returns_none_when_no_structured_data():
    with patch.object(recipe_import, "fetch_html", return_value=NO_STRUCTURED_DATA_HTML):
        assert recipe_import.parse_recipe_url("https://example.com/blog-post") is None


def test_fetch_html_returns_none_on_connection_error():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert recipe_import.fetch_html("https://example.com/anything") is None
