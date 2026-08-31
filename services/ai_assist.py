"""
AI Assist — optional, local-only assistive features via a locally-running
Ollama model. See docs/PRODUCT_SPEC.md §16 and docs/DECISIONS.md.

Isolated by design (docs/AGENT_INSTRUCTIONS.md §6): no core screen or
service imports this module, and every function here degrades gracefully
(returns None, or an empty/unfiltered result) rather than raising when the
model isn't reachable, isn't pulled, or returns something unparseable.
AI-suggested content is always a plain draft handed back to the caller for
review — nothing in this module writes to the database.
"""

import json
import os
import re
import urllib.request
from typing import Optional

from models import STORE_CATEGORIES, Recipe

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("AI_ASSIST_MODEL", "llama3.2")

_AVAILABILITY_TIMEOUT = 1.5
_GENERATE_TIMEOUT = 30.0
_URL_FETCH_TIMEOUT = 10.0


def is_available(*, host: str = OLLAMA_HOST, timeout: float = _AVAILABILITY_TIMEOUT) -> bool:
    """Whether a local Ollama server is reachable. Never raises — callers
    use this to decide whether to show AI-assisted UI at all."""
    try:
        request = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    host: str = OLLAMA_HOST,
    timeout: float = _GENERATE_TIMEOUT,
) -> Optional[str]:
    """Call Ollama's /api/generate and return the response text, or None on
    any failure — unreachable server, missing model, bad response, timeout.
    Never raises."""
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


def fetch_url_text(url: str, *, timeout: float = _URL_FETCH_TIMEOUT) -> Optional[str]:
    """Fetch a URL and return a best-effort plain-text version of its HTML
    (scripts/styles/tags stripped). Returns None on any failure. Never
    executes or renders the fetched content — only passed into a model
    prompt as text."""
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


def import_recipe_from_text(text: str, *, model: str = DEFAULT_MODEL) -> Optional[dict]:
    """Extract a structured recipe draft from pasted recipe text: name,
    servings, cook_time_minutes, instructions, and ingredient lines
    (name/quantity/unit). Returns None if the model is unavailable or its
    response can't be parsed. Never written to the database directly — the
    caller shows it as a pre-filled Add Recipe form for the user to review
    and confirm."""
    if not text or not text.strip():
        return None
    prompt = (
        "Extract structured recipe data from the recipe text below. "
        "Respond with ONLY a single JSON object, no markdown fences, no "
        "commentary, matching exactly this shape:\n"
        '{"name": string, "servings": integer, "cook_time_minutes": integer, '
        '"instructions": string, "ingredients": '
        '[{"name": string, "quantity": number or null, "unit": string or null}]}\n\n'
        f"Recipe text:\n{text.strip()}"
    )
    response = _generate(prompt, model=model)
    if response is None:
        return None
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


def suggest_store_category(ingredient_name: str, *, model: str = DEFAULT_MODEL) -> Optional[str]:
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
    response = _generate(prompt, model=model)
    if response is None:
        return None
    category = response.strip().strip(".").lower()
    return category if category in STORE_CATEGORIES else None


def narrow_candidates_by_intent(
    candidates: list[Recipe], intent: str, *, model: str = DEFAULT_MODEL
) -> Optional[list[Recipe]]:
    """Narrow a swap candidate list to those best matching a free-text
    intent hint (e.g. "vegetarian", "quicker", "use up the broccoli"),
    layered on top of the normal weighting in services/plan_generation.py.
    Returns a non-empty subset of `candidates`, or None if the model is
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


def suggest_shortcuts(recipe: Recipe, *, model: str = DEFAULT_MODEL) -> Optional[str]:
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
