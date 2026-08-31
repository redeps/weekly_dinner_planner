"""
Recipe photo storage — resize/compress on save, stored under photos/
named by the recipe's stable ID (never the display name, so a rename
never orphans the file). See docs/PRODUCT_SPEC.md §14.

Local filesystem only; the database stores a path reference
(recipes.photo_path), never a blob. photos/ is gitignored — never commit
household photos.
"""

import io
from pathlib import Path
from typing import Optional

from PIL import Image

PHOTOS_DIR = Path(__file__).resolve().parent.parent / "photos"

_MAX_DIMENSION = 1200
_JPEG_QUALITY = 85


def photo_relative_path(recipe_id: int) -> str:
    """The path stored in recipes.photo_path for a given recipe."""
    return f"photos/{recipe_id}.jpg"


def resolve_photo_path(photo_path: str) -> Path:
    """Resolve a recipes.photo_path value (e.g. "photos/7.jpg") to an
    absolute filesystem path, relative to PHOTOS_DIR's parent."""
    return PHOTOS_DIR.parent / photo_path


def save_recipe_photo(image_bytes: bytes, recipe_id: int) -> str:
    """Resize/compress an uploaded photo and save it under photos/, named
    by the recipe's stable ID — always a single normalized .jpg file per
    recipe, so uploading a new photo naturally replaces the old one.
    Returns the relative path to store in recipes.photo_path. Raises if
    `image_bytes` isn't a readable image — callers should show that to
    the user rather than swallow it, same as other save-path validation
    in this app."""
    PHOTOS_DIR.mkdir(exist_ok=True)
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGB")
    image.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
    relative_path = photo_relative_path(recipe_id)
    image.save(resolve_photo_path(relative_path), format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return relative_path


def delete_recipe_photo(recipe_id: int) -> None:
    """Remove a recipe's photo file, if any. Safe to call even if no
    photo exists."""
    resolve_photo_path(photo_relative_path(recipe_id)).unlink(missing_ok=True)


def photo_exists(photo_path: Optional[str]) -> bool:
    """Whether a recipe's stored photo_path actually has a file on disk —
    guards display code against a stale DB pointer to a removed file."""
    if not photo_path:
        return False
    return resolve_photo_path(photo_path).is_file()
