"""
Milestone 9 tests: AI Assist (services/ai_assist.py).

Mocks the model call throughout — no real Ollama server is contacted.
Every function is tested both for correct parsing of a valid model
response, and for graceful degradation (returns None / an empty or
unfiltered result, never raises) when the model is unreachable.
"""

import urllib.error
from unittest.mock import patch

import pytest

from models import Recipe
from services import ai_assist


def make_recipe(id=1, name="Recipe", seasonality="all-season", cook_time_minutes=30):
    return Recipe(
        id=id,
        name=name,
        photo_path=None,
        cook_time_minutes=cook_time_minutes,
        family_enjoyment=3,
        seasonality=seasonality,
        is_quick_fallback=False,
        servings=4,
        instructions="Cook it.",
        notes=None,
        active=True,
        created_at="",
        updated_at="",
    )


# --- is_available ---


def test_is_available_true_on_200_response():
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        assert ai_assist.is_available() is True


def test_is_available_false_when_connection_refused():
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError()):
        assert ai_assist.is_available() is False


def test_is_available_false_on_timeout():
    with patch("urllib.request.urlopen", side_effect=TimeoutError()):
        assert ai_assist.is_available() is False


def test_is_available_never_raises_on_unexpected_error():
    with patch("urllib.request.urlopen", side_effect=RuntimeError("something odd")):
        assert ai_assist.is_available() is False


# --- _generate (low-level) ---


def test_generate_returns_none_when_unreachable():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert ai_assist._generate("prompt") is None


def test_generate_returns_none_on_http_error():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("url", 404, "not found", None, None),
    ):
        assert ai_assist._generate("prompt") is None


# --- import_recipe_from_text ---


def test_import_recipe_from_text_parses_valid_response():
    fake_response = (
        '{"name": "Chicken Curry", "servings": 4, "cook_time_minutes": 30, '
        '"instructions": "Cook the chicken.\\nServe.", '
        '"ingredients": [{"name": "chicken", "quantity": 500, "unit": "g"}, '
        '{"name": "salt", "quantity": null, "unit": null}]}'
    )
    with patch.object(ai_assist, "_generate", return_value=fake_response):
        draft = ai_assist.import_recipe_from_text("some pasted recipe text")

    assert draft["name"] == "Chicken Curry"
    assert draft["servings"] == 4
    assert draft["cook_time_minutes"] == 30
    assert draft["instructions"] == "Cook the chicken.\nServe."
    assert draft["ingredients"] == [
        {"name": "chicken", "quantity": 500.0, "unit": "g"},
        {"name": "salt", "quantity": None, "unit": None},
    ]


def test_import_recipe_from_text_tolerates_markdown_fence():
    fake_response = '```json\n{"name": "Tacos", "servings": 2, "cook_time_minutes": 15, "instructions": "Assemble.", "ingredients": []}\n```'
    with patch.object(ai_assist, "_generate", return_value=fake_response):
        draft = ai_assist.import_recipe_from_text("taco recipe text")
    assert draft["name"] == "Tacos"


def test_import_recipe_from_text_returns_none_when_model_unreachable():
    with patch.object(ai_assist, "_generate", return_value=None):
        assert ai_assist.import_recipe_from_text("some text") is None


def test_import_recipe_from_text_returns_none_on_unparseable_response():
    with patch.object(ai_assist, "_generate", return_value="not json at all"):
        assert ai_assist.import_recipe_from_text("some text") is None


def test_import_recipe_from_text_returns_none_when_name_missing():
    with patch.object(ai_assist, "_generate", return_value='{"servings": 4}'):
        assert ai_assist.import_recipe_from_text("some text") is None


def test_import_recipe_from_text_returns_none_for_blank_input():
    assert ai_assist.import_recipe_from_text("") is None
    assert ai_assist.import_recipe_from_text("   ") is None


def test_import_recipe_from_text_defaults_bad_numeric_fields():
    fake_response = (
        '{"name": "Mystery Dish", "servings": "a lot", "cook_time_minutes": null, '
        '"instructions": "", "ingredients": []}'
    )
    with patch.object(ai_assist, "_generate", return_value=fake_response):
        draft = ai_assist.import_recipe_from_text("text")
    assert draft["servings"] == 4
    assert draft["cook_time_minutes"] == 30


# --- suggest_store_category ---


def test_suggest_store_category_returns_valid_category():
    with patch.object(ai_assist, "_generate", return_value="produce"):
        assert ai_assist.suggest_store_category("onion") == "produce"


def test_suggest_store_category_strips_and_lowercases():
    with patch.object(ai_assist, "_generate", return_value="  Produce.\n"):
        assert ai_assist.suggest_store_category("onion") == "produce"


def test_suggest_store_category_returns_none_for_invalid_category():
    with patch.object(ai_assist, "_generate", return_value="condiments"):
        assert ai_assist.suggest_store_category("ketchup") is None


def test_suggest_store_category_returns_none_when_unreachable():
    with patch.object(ai_assist, "_generate", return_value=None):
        assert ai_assist.suggest_store_category("onion") is None


def test_suggest_store_category_returns_none_for_blank_name():
    assert ai_assist.suggest_store_category("") is None
    assert ai_assist.suggest_store_category("   ") is None


# --- narrow_candidates_by_intent ---


def test_narrow_candidates_by_intent_returns_matching_subset():
    candidates = [make_recipe(1, "Chicken Curry"), make_recipe(2, "Veggie Stir Fry"), make_recipe(3, "Beef Tacos")]
    with patch.object(ai_assist, "_generate", return_value="[2]"):
        result = ai_assist.narrow_candidates_by_intent(candidates, "vegetarian")
    assert [r.id for r in result] == [2]


def test_narrow_candidates_by_intent_ignores_hallucinated_ids():
    candidates = [make_recipe(1, "Chicken Curry"), make_recipe(2, "Veggie Stir Fry")]
    with patch.object(ai_assist, "_generate", return_value="[2, 999]"):
        result = ai_assist.narrow_candidates_by_intent(candidates, "vegetarian")
    assert [r.id for r in result] == [2]


def test_narrow_candidates_by_intent_returns_none_when_all_ids_hallucinated():
    candidates = [make_recipe(1, "Chicken Curry")]
    with patch.object(ai_assist, "_generate", return_value="[999]"):
        assert ai_assist.narrow_candidates_by_intent(candidates, "vegetarian") is None


def test_narrow_candidates_by_intent_returns_none_when_unreachable():
    candidates = [make_recipe(1, "Chicken Curry")]
    with patch.object(ai_assist, "_generate", return_value=None):
        assert ai_assist.narrow_candidates_by_intent(candidates, "vegetarian") is None


def test_narrow_candidates_by_intent_returns_none_on_unparseable_response():
    candidates = [make_recipe(1, "Chicken Curry")]
    with patch.object(ai_assist, "_generate", return_value="sure, recipe 1 sounds good"):
        assert ai_assist.narrow_candidates_by_intent(candidates, "vegetarian") is None


def test_narrow_candidates_by_intent_returns_none_for_blank_intent():
    candidates = [make_recipe(1, "Chicken Curry")]
    assert ai_assist.narrow_candidates_by_intent(candidates, "") is None


def test_narrow_candidates_by_intent_returns_none_for_empty_candidates():
    assert ai_assist.narrow_candidates_by_intent([], "vegetarian") is None


# --- suggest_shortcuts ---


def test_suggest_shortcuts_returns_stripped_text():
    with patch.object(ai_assist, "_generate", return_value="  Use frozen chopped onion.\n"):
        result = ai_assist.suggest_shortcuts(make_recipe())
    assert result == "Use frozen chopped onion."


def test_suggest_shortcuts_returns_none_when_unreachable():
    with patch.object(ai_assist, "_generate", return_value=None):
        assert ai_assist.suggest_shortcuts(make_recipe()) is None


# --- fetch_url_text ---


def test_fetch_url_text_strips_tags_and_scripts():
    class FakeResponse:
        def __init__(self, html):
            self._html = html.encode("utf-8")

        def read(self):
            return self._html

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    html = "<html><head><style>.a{}</style><script>alert(1)</script></head><body><p>Chop onions.</p></body></html>"
    with patch("urllib.request.urlopen", return_value=FakeResponse(html)):
        text = ai_assist.fetch_url_text("http://example.com/recipe")
    assert "Chop onions." in text
    assert "alert" not in text
    assert "<p>" not in text


def test_fetch_url_text_returns_none_when_unreachable():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert ai_assist.fetch_url_text("http://example.com/recipe") is None
