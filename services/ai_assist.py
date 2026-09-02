"""
AI Assist — optional assistive features via a language model. See
docs/PRODUCT_SPEC.md §16c and docs/DECISIONS.md.

Two independent things live here, per docs/DECISIONS.md (Structured-data
recipe import; swappable AI backend):

- The text-only capabilities (ingredient categorization, swap-intent
  narrowing, shortcut suggestions, and the free-text/no-structured-data
  import fallback) select their backend from `AI_ASSIST_BACKEND`: local
  Ollama (default) or Google Gemini's free tier. Callers never see which
  backend is active — `is_available()` and every function below behave
  identically either way.
- Photo-based recipe import always calls Gemini directly, regardless of
  `AI_ASSIST_BACKEND`, since it needs a vision-capable model and no local
  vision model is supported (see docs/DECISIONS.md).

Isolated by design (docs/AGENT_INSTRUCTIONS.md §6): no core screen or
service imports this module, and every function here degrades gracefully
(returns None, or an empty/unfiltered result) rather than raising, whether
the cause is an unreachable server, a missing model/key, or a response
that doesn't parse as expected. AI-suggested content is always a plain
draft handed back to the caller for review — nothing in this module
writes to the database.
"""

import base64
import json
import os
import re
import urllib.request
from typing import Optional

from models import STORE_CATEGORIES, Recipe

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("AI_ASSIST_MODEL", "llama3.2")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# "-latest" alias, not a pinned snapshot, per the photo-import investigation
# (docs/DECISIONS.md) — gemini-flash-lite-latest measured fast and correct
# against the real API there, when gemini-flash-latest was timing out/
# overloaded. Still an alias to whatever Google currently routes it to, so
# this can go stale again the same way; not a permanent guarantee.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

_raw_backend = os.environ.get("AI_ASSIST_BACKEND", "ollama").strip().lower()
AI_ASSIST_BACKEND = _raw_backend if _raw_backend in ("ollama", "gemini") else "ollama"

_AVAILABILITY_TIMEOUT = 1.5
_GENERATE_TIMEOUT = 30.0
_URL_FETCH_TIMEOUT = 10.0
# Short-lived on purpose: suggest_store_category() is a best-effort,
# skippable suggestion, not worth a long wait — see docs/DECISIONS.md
# (the investigation that found gemini-flash-latest hanging up to the
# full 30s timeout per call, turning a 6-ingredient batch into 3+ minutes).
_CATEGORY_SUGGESTION_TIMEOUT = 6.0

_IMPORT_JSON_SHAPE = (
    '{"name": string, "servings": integer, "cook_time_minutes": integer, '
    '"instructions": string, "ingredients": '
    '[{"name": string, "quantity": number or null, "unit": string or null}]}'
)


# --- backend-agnostic text generation (Ollama or Gemini) ---


def is_available() -> bool:
    """Whether the currently configured text backend (AI_ASSIST_BACKEND)
    is usable. Never raises — callers use this to decide whether to show
    AI-assisted UI at all."""
    if AI_ASSIST_BACKEND == "gemini":
        return bool(GEMINI_API_KEY)
    return _ollama_reachable(OLLAMA_HOST)


def backend_status_note() -> Optional[str]:
    """One-line diagnostic for a specific, easy-to-hit misconfiguration:
    a Gemini key is present but AI_ASSIST_BACKEND is still "ollama" (the
    default — see Milestone 10: backend selection is explicit config,
    never automatic fallback) and no Ollama server is reachable. In that
    case every text-only AI Assist feature (categorization, swap-intent,
    shortcuts, the text-import fallback) just doesn't render — is_available()
    alone gives no hint why, which is exactly the failure mode that bit a
    real hosted deployment (GEMINI_API_KEY set, AI_ASSIST_BACKEND never
    set). Returns None when nothing looks off. Never raises."""
    if AI_ASSIST_BACKEND == "ollama" and GEMINI_API_KEY and not _ollama_reachable(OLLAMA_HOST):
        return (
            "GEMINI_API_KEY is set, but AI_ASSIST_BACKEND is still \"ollama\" "
            "(the default) and no Ollama server is reachable — text-based AI "
            "Assist features (categorization, swap-intent, shortcuts) are "
            "disabled. Set AI_ASSIST_BACKEND=gemini to use Gemini for those too."
        )
    return None


def _ollama_reachable(host: str, *, timeout: float = _AVAILABILITY_TIMEOUT) -> bool:
    try:
        request = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _generate_ollama(
    prompt: str, *, model: str, host: str = OLLAMA_HOST, timeout: float = _GENERATE_TIMEOUT
) -> Optional[str]:
    """Call Ollama's /api/generate. Returns the response text, or None on
    any failure. Never raises."""
    try:
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body.get("response")
    except Exception:
        return None


def _call_gemini(
    parts: list[dict], *, model: str, api_key: str, timeout: float = _GENERATE_TIMEOUT
) -> Optional[str]:
    """Low-level Gemini generateContent call — `parts` may mix
    {"text": ...} and {"inline_data": {"mime_type": ..., "data": ...}}
    entries, so this backs both text and photo (vision) calls. Returns the
    response text, or None on any failure. Never raises."""
    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None


def _generate(prompt: str, *, model: Optional[str] = None, timeout: float = _GENERATE_TIMEOUT) -> Optional[str]:
    """Call the currently configured text backend and return the response
    text, or None on any failure — unreachable server, missing model/key,
    bad response, timeout. Never raises. Every text-only capability below
    is built on this and is backend-agnostic."""
    if AI_ASSIST_BACKEND == "gemini":
        if not GEMINI_API_KEY:
            return None
        return _call_gemini(
            [{"text": prompt}], model=model or GEMINI_MODEL, api_key=GEMINI_API_KEY, timeout=timeout
        )
    return _generate_ollama(prompt, model=model or DEFAULT_MODEL, timeout=timeout)


def _extract_json(text: str):
    """Best-effort JSON extraction from a model response, tolerating a
    ```json fence or surrounding commentary. Returns None if no valid JSON
    object/array is found."""
    if not text:
        return None
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _draft_from_model_response(response: str) -> Optional[dict]:
    """Shared JSON-to-draft coercion for both the text and photo import
    paths (see _IMPORT_JSON_SHAPE)."""
    data = _extract_json(response)
    if not isinstance(data, dict) or not data.get("name"):
        return None

    def _coerce_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    ingredients = []
    for item in data.get("ingredients") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        quantity = item.get("quantity")
        try:
            quantity = float(quantity) if quantity is not None else None
        except (TypeError, ValueError):
            quantity = None
        ingredients.append(
            {
                "name": str(item["name"]).strip(),
                "quantity": quantity,
                "unit": str(item["unit"]).strip() if item.get("unit") else None,
            }
        )

    return {
        "name": str(data["name"]).strip(),
        "servings": _coerce_int(data.get("servings"), 4),
        "cook_time_minutes": _coerce_int(data.get("cook_time_minutes"), 30),
        "instructions": str(data.get("instructions") or "").strip() or None,
        "ingredients": ingredients,
    }


def fetch_url_text(url: str, *, timeout: float = _URL_FETCH_TIMEOUT) -> Optional[str]:
    """Fetch a URL and return a best-effort plain-text version of its HTML
    (scripts/styles/tags stripped). Returns None on any failure. Never
    executes or renders the fetched content — only passed into a model
    prompt as text. Used as the text-import fallback's own fetch when the
    primary structured-data path (services/recipe_import.py) finds
    nothing to parse."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def import_recipe_from_text(text: str, *, model: Optional[str] = None) -> Optional[dict]:
    """Extract a structured recipe draft from pasted recipe text: name,
    servings, cook_time_minutes, instructions, and ingredient lines
    (name/quantity/unit). This is the fallback import path — used only
    for pasted free text, or a URL whose page has no schema.org/Recipe
    structured data (see services/recipe_import.py, the primary path).
    Returns None if the backend is unavailable or its response can't be
    parsed. Never written to the database directly — the caller shows it
    as a pre-filled Add Recipe form for the user to review and confirm."""
    if not text or not text.strip():
        return None
    prompt = (
        "Extract structured recipe data from the recipe text below. "
        "Respond with ONLY a single JSON object, no markdown fences, no "
        f"commentary, matching exactly this shape:\n{_IMPORT_JSON_SHAPE}\n\n"
        f"Recipe text:\n{text.strip()}"
    )
    response = _generate(prompt, model=model)
    if response is None:
        return None
    return _draft_from_model_response(response)


def suggest_store_category(ingredient_name: str, *, model: Optional[str] = None) -> Optional[str]:
    """Suggest a store_category for an ingredient name. Returns one of
    models.STORE_CATEGORIES, or None if unavailable or the response
    doesn't match a known category. The caller always leaves this
    overridable."""
    if not ingredient_name or not ingredient_name.strip():
        return None
    categories = ", ".join(STORE_CATEGORIES)
    prompt = (
        f"Categorize this grocery ingredient into exactly one of these "
        f"categories: {categories}. Respond with ONLY the category word, "
        f"nothing else.\n\nIngredient: {ingredient_name.strip()}"
    )
    response = _generate(prompt, model=model, timeout=_CATEGORY_SUGGESTION_TIMEOUT)
    if response is None:
        return None
    category = response.strip().strip(".").lower()
    return category if category in STORE_CATEGORIES else None


def narrow_candidates_by_intent(
    candidates: list[Recipe], intent: str, *, model: Optional[str] = None
) -> Optional[list[Recipe]]:
    """Narrow a swap candidate list to those best matching a free-text
    intent hint (e.g. "vegetarian", "quicker", "use up the broccoli"),
    layered on top of the normal weighting in services/plan_generation.py.
    Returns a non-empty subset of `candidates`, or None if the backend is
    unavailable, its response can't be parsed, or nothing it returned
    matches an actual candidate — callers must treat None as "use the
    full list", never as "no matches"."""
    if not candidates or not intent or not intent.strip():
        return None
    listing = "\n".join(f"{r.id}: {r.name}" for r in candidates)
    prompt = (
        "Given this intent hint from a home cook and a list of candidate "
        "recipes (id: name), return ONLY a JSON array of the ids that best "
        f'fit the intent, e.g. [1, 4]. Intent: "{intent.strip()}"\n\n'
        f"Candidates:\n{listing}"
    )
    response = _generate(prompt, model=model)
    if response is None:
        return None
    ids = _extract_json(response)
    if not isinstance(ids, list):
        return None
    valid_ids = {r.id for r in candidates}
    matched_ids = [i for i in ids if isinstance(i, int) and i in valid_ids]
    if not matched_ids:
        return None
    by_id = {r.id: r for r in candidates}
    return [by_id[i] for i in matched_ids]


def suggest_shortcuts(recipe: Recipe, *, model: Optional[str] = None) -> Optional[str]:
    """Suggest up to 3 short effort-saving substitutions for a recipe, as
    plain text for display alongside it — never persisted. Returns None if
    unavailable."""
    prompt = (
        "Suggest up to 3 short, practical effort-saving substitutions or "
        "shortcuts for this home-cooked recipe (e.g. using a frozen or "
        "pre-prepared ingredient instead of a fresh one). One per line, no "
        "numbering, no extra commentary.\n\n"
        f"Recipe: {recipe.name}\n"
        f"Instructions: {recipe.instructions or '(none)'}"
    )
    response = _generate(prompt, model=model)
    return response.strip() if response else None


# --- photo import: always Gemini, independent of AI_ASSIST_BACKEND ---


def is_photo_import_available() -> bool:
    """Whether photo-based recipe import is usable. Always Gemini,
    regardless of AI_ASSIST_BACKEND — see docs/DECISIONS.md."""
    return bool(GEMINI_API_KEY)


def import_recipe_from_photo(image_bytes: bytes, *, mime_type: str = "image/jpeg") -> Optional[dict]:
    """Extract a structured recipe draft from a single photo of a
    cookbook page or recipe card. Thin wrapper around
    import_recipe_from_photos() for the common one-photo case — see that
    function for the full contract."""
    return import_recipe_from_photos([(image_bytes, mime_type)])


def import_recipe_from_photos(images: list[tuple[bytes, str]]) -> Optional[dict]:
    """Extract a structured recipe draft from one or more photos of a
    cookbook page or recipe card (e.g. the front and back of one card, or
    multiple pages of one recipe), via Gemini's vision capability —
    always Gemini, regardless of AI_ASSIST_BACKEND (see
    docs/DECISIONS.md), since this needs a vision-capable model and no
    local one is supported. All photos are sent as separate inline_data
    parts within a single call, not one call per photo — confirmed
    against the real API to work, and it avoids reconciling multiple
    independently-generated drafts that might disagree (see
    docs/DECISIONS.md). `images` is a list of (image_bytes, mime_type)
    pairs. Returns None if no Gemini key is configured, `images` is
    empty, or the response can't be parsed. Never written to the
    database directly — shown as a pre-filled Add Recipe form for the
    user to review and confirm, same as the other import paths."""
    images = [(data, mime) for data, mime in images if data]
    if not GEMINI_API_KEY or not images:
        return None
    plural = "photo" if len(images) == 1 else f"{len(images)} photos of the same recipe"
    prompt = (
        f"Extract structured recipe data from this {plural} (a cookbook "
        "page or recipe card). Respond with ONLY a single JSON object, no "
        f"markdown fences, no commentary, matching exactly this shape:\n"
        f"{_IMPORT_JSON_SHAPE}"
    )
    parts = [{"text": prompt}] + [
        {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("ascii"),
            }
        }
        for image_bytes, mime_type in images
    ]
    response = _call_gemini(parts, model=GEMINI_MODEL, api_key=GEMINI_API_KEY)
    if response is None:
        return None
    return _draft_from_model_response(response)
