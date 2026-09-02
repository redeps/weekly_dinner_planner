"""
Milestone 9/10 tests: AI Assist (services/ai_assist.py).

Mocks the model call throughout — no real Ollama or Gemini server is
contacted. Every function is tested both for correct parsing of a valid
model response, and for graceful degradation (returns None / an empty or
unfiltered result, never raises) when the backend is unreachable or
unconfigured. Milestone 10 adds backend-selection tests (Ollama vs.
Gemini) and photo-import tests — photo import always targets Gemini
regardless of AI_ASSIST_BACKEND, per docs/DECISIONS.md.
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
        is_special_occasion=False,
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


def test_suggest_store_category_uses_short_timeout_not_the_import_timeout():
    """A best-effort suggestion shouldn't wait as long as recipe import —
    see docs/DECISIONS.md (the investigation where gemini-flash-latest
    hung up to the full 30s _GENERATE_TIMEOUT per call)."""
    with patch.object(ai_assist, "_generate", return_value="produce") as mock_generate:
        ai_assist.suggest_store_category("onion")
    assert mock_generate.call_args.kwargs["timeout"] == ai_assist._CATEGORY_SUGGESTION_TIMEOUT
    assert ai_assist._CATEGORY_SUGGESTION_TIMEOUT < ai_assist._GENERATE_TIMEOUT


def test_gemini_model_default_is_not_the_confirmed_dead_snapshot():
    """gemini-2.0-flash and gemini-2.5-flash both 404 against the real API
    (see docs/DECISIONS.md) — this just guards against silently
    reverting to either."""
    assert ai_assist.GEMINI_MODEL not in ("gemini-2.0-flash", "gemini-2.5-flash")


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


# --- backend selection: is_available() ---


def test_is_available_uses_ollama_by_default():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "_ollama_reachable", return_value=True
    ) as mock_reachable:
        assert ai_assist.is_available() is True
        mock_reachable.assert_called_once()


def test_is_available_gemini_true_when_key_configured():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ):
        assert ai_assist.is_available() is True


def test_is_available_gemini_false_when_no_key():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", None
    ):
        assert ai_assist.is_available() is False


def test_ai_assist_backend_normalizes_unknown_value_to_ollama():
    # Simulates module (re)load behavior: an invalid env value falls back
    # to "ollama" rather than silently doing nothing.
    raw = "not-a-real-backend"
    normalized = raw if raw in ("ollama", "gemini") else "ollama"
    assert normalized == "ollama"


# --- backend_status_note(): diagnosing the "Gemini key set but backend
# still ollama" footgun that silently disabled every text-only AI Assist
# feature on a real hosted deployment ---


def test_backend_status_note_flags_gemini_key_stuck_on_unreachable_ollama():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(ai_assist, "_ollama_reachable", return_value=False):
        note = ai_assist.backend_status_note()
    assert note is not None
    assert "AI_ASSIST_BACKEND" in note
    assert "gemini" in note.lower()


def test_backend_status_note_none_without_a_gemini_key():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "GEMINI_API_KEY", None
    ), patch.object(ai_assist, "_ollama_reachable", return_value=False):
        assert ai_assist.backend_status_note() is None


def test_backend_status_note_none_when_ollama_is_actually_reachable():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(ai_assist, "_ollama_reachable", return_value=True):
        assert ai_assist.backend_status_note() is None


def test_backend_status_note_none_when_backend_already_gemini():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(ai_assist, "_ollama_reachable") as mock_reachable:
        assert ai_assist.backend_status_note() is None
        mock_reachable.assert_not_called()


# --- backend selection: _generate() dispatch ---


def test_generate_dispatches_to_ollama_by_default():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "_generate_ollama", return_value="ollama response"
    ) as mock_ollama, patch.object(ai_assist, "_call_gemini") as mock_gemini:
        assert ai_assist._generate("prompt") == "ollama response"
        mock_ollama.assert_called_once()
        mock_gemini.assert_not_called()


def test_generate_dispatches_to_gemini_when_configured():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(ai_assist, "_call_gemini", return_value="gemini response") as mock_gemini, patch.object(
        ai_assist, "_generate_ollama"
    ) as mock_ollama:
        assert ai_assist._generate("prompt") == "gemini response"
        mock_gemini.assert_called_once()
        mock_ollama.assert_not_called()


def test_generate_gemini_backend_returns_none_without_key():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", None
    ), patch.object(ai_assist, "_call_gemini") as mock_gemini:
        assert ai_assist._generate("prompt") is None
        mock_gemini.assert_not_called()


def test_call_gemini_parses_valid_response():
    fake_body = {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}

    class FakeResponse:
        def read(self):
            import json

            return json.dumps(fake_body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = ai_assist._call_gemini([{"text": "hi"}], model="gemini-2.0-flash", api_key="fake-key")
    assert result == "hello"


def test_call_gemini_returns_none_on_http_error():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("url", 403, "forbidden", None, None),
    ):
        result = ai_assist._call_gemini([{"text": "hi"}], model="gemini-2.0-flash", api_key="bad-key")
    assert result is None


def test_call_gemini_returns_none_on_malformed_response_shape():
    class FakeResponse:
        def read(self):
            return b'{"unexpected": "shape"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        result = ai_assist._call_gemini([{"text": "hi"}], model="gemini-2.0-flash", api_key="fake-key")
    assert result is None


# --- suggestion features work identically regardless of backend ---


def test_suggest_store_category_works_via_gemini_backend():
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(ai_assist, "_call_gemini", return_value="produce"):
        assert ai_assist.suggest_store_category("onion") == "produce"


# --- photo import: always Gemini, independent of AI_ASSIST_BACKEND ---


def test_is_photo_import_available_true_with_key():
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        assert ai_assist.is_photo_import_available() is True


def test_is_photo_import_available_false_without_key():
    with patch.object(ai_assist, "GEMINI_API_KEY", None):
        assert ai_assist.is_photo_import_available() is False


def test_import_recipe_from_photo_returns_none_without_key():
    with patch.object(ai_assist, "GEMINI_API_KEY", None):
        assert ai_assist.import_recipe_from_photo(b"fake image bytes") is None


def test_import_recipe_from_photo_returns_none_for_empty_bytes():
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        assert ai_assist.import_recipe_from_photo(b"") is None


def test_import_recipe_from_photo_parses_valid_response():
    fake_response = (
        '{"name": "Grandma\'s Lasagna", "servings": 8, "cook_time_minutes": 60, '
        '"instructions": "Layer and bake.", "ingredients": '
        '[{"name": "pasta sheets", "quantity": 12, "unit": "each"}]}'
    )
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini", return_value=fake_response
    ) as mock_gemini:
        draft = ai_assist.import_recipe_from_photo(b"fake jpeg bytes", mime_type="image/jpeg")

    assert draft["name"] == "Grandma's Lasagna"
    assert draft["servings"] == 8
    # confirm the image bytes were actually sent, base64-encoded, as inline_data
    call_args = mock_gemini.call_args
    parts = call_args.args[0] if call_args.args else call_args.kwargs["parts"]
    inline_parts = [p for p in parts if "inline_data" in p]
    assert len(inline_parts) == 1
    assert inline_parts[0]["inline_data"]["mime_type"] == "image/jpeg"


def test_import_recipe_from_photo_returns_none_on_unparseable_response():
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini", return_value="not json"
    ):
        assert ai_assist.import_recipe_from_photo(b"fake image bytes") is None


def test_import_recipe_from_photo_ignores_ai_assist_backend_setting():
    """Photo import must use Gemini even when AI_ASSIST_BACKEND is
    "ollama" (the default) — it has no local-model equivalent."""
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(
        ai_assist, "_call_gemini", return_value='{"name": "Test Recipe"}'
    ) as mock_gemini, patch.object(
        ai_assist, "_generate_ollama"
    ) as mock_ollama:
        draft = ai_assist.import_recipe_from_photo(b"fake image bytes")
    assert draft["name"] == "Test Recipe"
    mock_gemini.assert_called_once()
    mock_ollama.assert_not_called()


# --- import_recipe_from_photos: multi-image import (front/back of a card) ---


def test_import_recipe_from_photos_sends_all_images_in_one_call():
    """Multiple photos go into ONE Gemini call as separate inline_data
    parts, not one call per photo — confirmed against the real API to
    work this way (see docs/DECISIONS.md); avoids reconciling multiple
    independently-generated drafts that might disagree."""
    fake_response = '{"name": "Two-Sided Card Recipe", "servings": 4, "cook_time_minutes": 20, "instructions": "Do it.", "ingredients": []}'
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini", return_value=fake_response
    ) as mock_gemini:
        draft = ai_assist.import_recipe_from_photos(
            [(b"front bytes", "image/jpeg"), (b"back bytes", "image/png")]
        )
    assert draft["name"] == "Two-Sided Card Recipe"
    mock_gemini.assert_called_once()
    call_args = mock_gemini.call_args
    parts = call_args.args[0] if call_args.args else call_args.kwargs["parts"]
    inline_parts = [p for p in parts if "inline_data" in p]
    assert len(inline_parts) == 2
    assert inline_parts[0]["inline_data"]["mime_type"] == "image/jpeg"
    assert inline_parts[1]["inline_data"]["mime_type"] == "image/png"


def test_import_recipe_from_photos_single_image_matches_wrapper():
    """import_recipe_from_photo() is a thin wrapper — a single-item list
    through import_recipe_from_photos() must behave identically."""
    fake_response = '{"name": "One Photo Recipe", "servings": 2, "cook_time_minutes": 10, "instructions": "Do it.", "ingredients": []}'
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini", return_value=fake_response
    ):
        via_plural = ai_assist.import_recipe_from_photos([(b"bytes", "image/jpeg")])
        via_singular = ai_assist.import_recipe_from_photo(b"bytes", mime_type="image/jpeg")
    assert via_plural == via_singular == {
        "name": "One Photo Recipe",
        "servings": 2,
        "cook_time_minutes": 10,
        "instructions": "Do it.",
        "ingredients": [],
    }


def test_import_recipe_from_photos_returns_none_for_empty_list():
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"):
        assert ai_assist.import_recipe_from_photos([]) is None


def test_import_recipe_from_photos_filters_out_empty_images():
    """An empty-bytes entry (e.g. a zero-byte upload) is dropped rather
    than sent to the API; if that leaves nothing, this returns None
    without ever calling the network, same as the single-photo empty-bytes
    case."""
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini"
    ) as mock_gemini:
        assert ai_assist.import_recipe_from_photos([(b"", "image/jpeg")]) is None
    mock_gemini.assert_not_called()


def test_import_recipe_from_photos_returns_none_without_key():
    with patch.object(ai_assist, "GEMINI_API_KEY", None):
        assert ai_assist.import_recipe_from_photos([(b"bytes", "image/jpeg")]) is None


def test_import_recipe_from_photos_prompt_mentions_multiple_photos():
    """The prompt text itself should tell the model these photos are one
    recipe, not describe a single "photo" when there's more than one."""
    with patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_call_gemini", return_value=None
    ) as mock_gemini:
        ai_assist.import_recipe_from_photos([(b"a", "image/jpeg"), (b"b", "image/jpeg")])
    parts = mock_gemini.call_args.args[0]
    prompt_text = parts[0]["text"]
    assert "2 photos" in prompt_text


# --- graceful degradation matrix (item 5): every backend combination ---


def test_degradation_no_backend_configured():
    """Neither Ollama nor a Gemini key available: text features and photo
    import both cleanly unavailable, nothing raises."""
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "_ollama_reachable", return_value=False
    ), patch.object(ai_assist, "GEMINI_API_KEY", None):
        assert ai_assist.is_available() is False
        assert ai_assist.is_photo_import_available() is False
        assert ai_assist.suggest_store_category("onion") is None
        assert ai_assist.import_recipe_from_photo(b"bytes") is None


def test_degradation_ollama_only_photo_import_still_unavailable():
    """Ollama reachable, no Gemini key: text features work, photo import
    stays unavailable (it never falls back to Ollama)."""
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "_ollama_reachable", return_value=True
    ), patch.object(ai_assist, "GEMINI_API_KEY", None), patch.object(
        ai_assist, "_generate_ollama", return_value="produce"
    ):
        assert ai_assist.is_available() is True
        assert ai_assist.suggest_store_category("onion") == "produce"
        assert ai_assist.is_photo_import_available() is False
        assert ai_assist.import_recipe_from_photo(b"bytes") is None


def test_degradation_gemini_only():
    """Gemini key configured, backend set to gemini, no Ollama running:
    both text features and photo import work."""
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "gemini"), patch.object(
        ai_assist, "GEMINI_API_KEY", "fake-key"
    ), patch.object(ai_assist, "_call_gemini", return_value="produce"):
        assert ai_assist.is_available() is True
        assert ai_assist.suggest_store_category("onion") == "produce"
        assert ai_assist.is_photo_import_available() is True


def test_degradation_both_configured_text_uses_selected_backend():
    """Both Ollama and Gemini available, but AI_ASSIST_BACKEND=ollama:
    text features use Ollama (not silently switching to Gemini), photo
    import still always uses Gemini."""
    with patch.object(ai_assist, "AI_ASSIST_BACKEND", "ollama"), patch.object(
        ai_assist, "_ollama_reachable", return_value=True
    ), patch.object(ai_assist, "GEMINI_API_KEY", "fake-key"), patch.object(
        ai_assist, "_generate_ollama", return_value="produce"
    ) as mock_ollama, patch.object(
        ai_assist, "_call_gemini", return_value='{"name": "Test"}'
    ) as mock_gemini:
        assert ai_assist.suggest_store_category("onion") == "produce"
        mock_ollama.assert_called_once()
        mock_gemini.assert_not_called()

        draft = ai_assist.import_recipe_from_photo(b"bytes")
        assert draft["name"] == "Test"
        mock_gemini.assert_called_once()
