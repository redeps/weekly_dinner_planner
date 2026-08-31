"""
Recipe import from a URL — parses embedded schema.org/Recipe JSON-LD
structured data. See docs/PRODUCT_SPEC.md §16a and docs/DECISIONS.md.

Deterministic and free: no model call, works with no AI backend
configured at all. Standard library only (urllib, html.parser, json) —
deliberately not a third-party scraping package; see docs/DECISIONS.md.
This is the primary URL import path. When a page has no structured
Recipe data, callers fall back to services/ai_assist.import_recipe_from_text().
"""

import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import Optional

_FETCH_TIMEOUT = 10.0


def fetch_html(url: str, *, timeout: float = _FETCH_TIMEOUT) -> Optional[str]:
    """Fetch a URL's raw HTML. Returns None on any failure."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


class _JSONLDExtractor(HTMLParser):
    """Collects the text content of every
    <script type="application/ld+json"> block in an HTML document."""

    def __init__(self):
        super().__init__()
        self._in_ld_json = False
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            attr_dict = dict(attrs)
            if (attr_dict.get("type") or "").lower() == "application/ld+json":
                self._in_ld_json = True
                self.blocks.append("")

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self._in_ld_json = False

    def handle_data(self, data):
        if self._in_ld_json and self.blocks:
            self.blocks[-1] += data


def _iter_recipe_dicts(node):
    """Yield every dict in a parsed JSON-LD structure whose @type includes
    "Recipe" — handling a bare object, a list of objects, and @graph
    nesting (common with SEO plugins)."""
    if isinstance(node, dict):
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(isinstance(t, str) and t.lower() == "recipe" for t in types):
            yield node
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_recipe_dicts(item)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_recipe_dicts(item)


def extract_json_ld_recipe(html: str) -> Optional[dict]:
    """Find and return the first schema.org Recipe JSON-LD block in an
    HTML document, or None if none is present or parseable."""
    if not html:
        return None
    parser = _JSONLDExtractor()
    try:
        parser.feed(html)
    except Exception:
        return None
    for block in parser.blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for recipe in _iter_recipe_dicts(data):
            return recipe
    return None


def _parse_iso8601_duration_minutes(value) -> Optional[int]:
    """Parse an ISO 8601 duration like "PT1H15M" into whole minutes."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value.strip())
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 60 + minutes + (1 if seconds else 0)


def _coerce_servings(value) -> Optional[int]:
    """recipeYield can be an int, a numeric string, "4 servings", or a
    list of any of those — pull out the first integer found."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _coerce_instructions(value) -> Optional[str]:
    """recipeInstructions can be a plain string, a list of strings, or a
    list of HowToStep objects (optionally nested under
    HowToSection.itemListElement) — normalize to newline-joined step
    text, matching Cook Mode's own line-based splitting
    (services/cook_mode.py)."""
    if value is None:
        return None
    if isinstance(value, str):
        lines = [line.strip() for line in re.split(r"</?p>|\n", value) if line.strip()]
        return "\n".join(lines) if lines else value.strip()

    steps: list[str] = []

    def _walk(node):
        if isinstance(node, str):
            text = node.strip()
            if text:
                steps.append(text)
        elif isinstance(node, dict):
            node_type = node.get("@type", "")
            if isinstance(node_type, str) and node_type.lower() == "howtosection":
                for item in node.get("itemListElement") or []:
                    _walk(item)
            else:
                text = node.get("text") or node.get("name")
                if text:
                    steps.append(str(text).strip())
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(value)
    return "\n".join(steps) if steps else None


def _coerce_ingredients(value) -> list[dict]:
    """recipeIngredient is typically a flat list of free-text lines (e.g.
    "2 cups flour") — schema.org doesn't split them into name/quantity/
    unit, and parsing that out reliably needs exactly the kind of
    scraping-library logic this module deliberately avoids (see
    docs/DECISIONS.md), so each line becomes one ingredient row with the
    full text as its name; the user can split it manually afterward if
    they want grocery-list aggregation to match units."""
    if not isinstance(value, list):
        return []
    ingredients = []
    for line in value:
        text = str(line).strip()
        if text:
            ingredients.append({"name": text, "quantity": None, "unit": None})
    return ingredients


def recipe_draft_from_json_ld(data: dict) -> Optional[dict]:
    """Map a parsed schema.org/Recipe JSON-LD dict to our draft shape.
    Returns None if there's no usable name."""
    name = data.get("name")
    if not name or not str(name).strip():
        return None

    cook_time = (
        _parse_iso8601_duration_minutes(data.get("cookTime"))
        or _parse_iso8601_duration_minutes(data.get("totalTime"))
        or _parse_iso8601_duration_minutes(data.get("prepTime"))
    )

    return {
        "name": str(name).strip(),
        "servings": _coerce_servings(data.get("recipeYield")) or 4,
        "cook_time_minutes": cook_time if cook_time is not None else 30,
        "instructions": _coerce_instructions(data.get("recipeInstructions")),
        "ingredients": _coerce_ingredients(data.get("recipeIngredient")),
    }


def parse_recipe_url(url: str, *, timeout: float = _FETCH_TIMEOUT) -> Optional[dict]:
    """Fetch a URL and extract a recipe draft from its embedded
    schema.org/Recipe JSON-LD, if present. Returns None if the page can't
    be fetched, has no structured Recipe data, or that data has no usable
    name — callers should fall back to the AI-assist text parser in that
    case (services/ai_assist.import_recipe_from_text)."""
    html = fetch_html(url, timeout=timeout)
    if html is None:
        return None
    data = extract_json_ld_recipe(html)
    if data is None:
        return None
    return recipe_draft_from_json_ld(data)
