"""
Recipe photo storage — resize/compress on save, stored under photos/
named by the recipe's stable ID (never the display name, so a rename
never orphans the file). See docs/PRODUCT_SPEC.md §14.

Milestone 13 Phase 3: the local filesystem is always the persistent store
when no `st.secrets["r2"]` is configured (local dev, per docs/DECISIONS.md
— Milestone 13 hosting architecture), and always acts as a local cache
even when R2 *is* configured — save/delete additionally sync to
Cloudflare R2 via `boto3`, and a cache miss on read transparently
downloads from R2 first. This means every existing call site
(`photo_exists()` / `resolve_photo_path()`, used by every page that
displays a photo) keeps returning exactly what it always has — a bool /
a local filesystem Path — with no page changes needed for R2 support.

Most R2-specific failures (missing credentials, network error, etc.) are
caught and swallowed, never raised — reads (`photo_exists()` /
`resolve_photo_path()`'s cache-miss download) and deletes always degrade
to local-only behavior, matching this codebase's existing "optional
hosted dependency never breaks a core screen" principle
(docs/AGENT_INSTRUCTIONS.md §6; the AI Assist graceful-degradation
entries in docs/DECISIONS.md). `save_recipe_photo()` is the one
exception: local disk isn't durable in the actual production deployment
(it doesn't survive a Streamlit Community Cloud restart), so a failed R2
sync there raises `PhotoBackupError` instead of swallowing — see that
function's docstring and docs/DECISIONS.md ("Phase 3 durability fix") for
the full reasoning, including why backend selection is "is
`st.secrets['r2']` configured?" rather than a separate env var toggle
like `AI_ASSIST_BACKEND`.

The database stores a path reference (recipes.photo_path), never a blob.
photos/ is gitignored — never commit household photos.
"""

import io
import logging
from pathlib import Path
from typing import Optional

import boto3
import streamlit as st
from PIL import Image

PHOTOS_DIR = Path(__file__).resolve().parent.parent / "photos"

_MAX_DIMENSION = 1200
_JPEG_QUALITY = 85

logger = logging.getLogger(__name__)


def photo_relative_path(recipe_id: int) -> str:
    """The path stored in recipes.photo_path for a given recipe — also
    the R2 object key when R2 is configured, unchanged (docs/DECISIONS.md)."""
    return f"photos/{recipe_id}.jpg"


def _local_path(photo_path: str) -> Path:
    return PHOTOS_DIR.parent / photo_path


def resolve_photo_path(photo_path: str) -> Path:
    """Resolve a recipes.photo_path value (e.g. "photos/7.jpg") to an
    absolute filesystem path, relative to PHOTOS_DIR's parent. If R2 is
    configured and the file isn't in the local cache, downloads it from
    R2 first (best-effort — see module docstring)."""
    local_path = _local_path(photo_path)
    if not local_path.is_file() and _r2_configured():
        _download_from_r2(photo_path, local_path)
    return local_path


def _r2_configured() -> bool:
    try:
        return bool(st.secrets.get("r2"))
    except Exception:
        return False


def _r2_client():
    secrets = st.secrets["r2"]
    return boto3.client(
        "s3",
        endpoint_url=secrets["endpoint_url"],
        aws_access_key_id=secrets["aws_access_key_id"],
        aws_secret_access_key=secrets["aws_secret_access_key"],
        region_name="auto",
    )


def _r2_bucket() -> str:
    return st.secrets["r2"]["bucket_name"]


def _upload_to_r2(local_path: Path, key: str) -> bool:
    try:
        _r2_client().upload_file(
            str(local_path), _r2_bucket(), key, ExtraArgs={"ContentType": "image/jpeg"}
        )
        return True
    except Exception:
        logger.warning("R2 upload failed for %s; local copy is unaffected", key, exc_info=True)
        return False


def _download_from_r2(key: str, local_path: Path) -> None:
    try:
        PHOTOS_DIR.mkdir(exist_ok=True)
        _r2_client().download_file(_r2_bucket(), key, str(local_path))
    except Exception:
        logger.warning("R2 download failed for %s; falling back to local-only", key, exc_info=True)


def _delete_from_r2(key: str) -> None:
    try:
        _r2_client().delete_object(Bucket=_r2_bucket(), Key=key)
    except Exception:
        logger.warning("R2 delete failed for %s", key, exc_info=True)


def _r2_object_exists(key: str) -> bool:
    try:
        _r2_client().head_object(Bucket=_r2_bucket(), Key=key)
        return True
    except Exception:
        return False


class PhotoBackupError(Exception):
    """Raised by save_recipe_photo when the local save succeeded but
    syncing it to R2 failed. Distinct from a plain image-processing
    failure (an unreadable upload): here the photo *is* saved and usable
    for the rest of this session, it just isn't durable yet — see
    docs/DECISIONS.md ("Phase 3 durability fix"). Carries `relative_path`
    so the caller can still record it in recipes.photo_path; the local
    file is real and already on disk when this is raised."""

    def __init__(self, relative_path: str):
        self.relative_path = relative_path
        super().__init__(f"R2 backup failed for {relative_path}; local copy was saved")


def save_recipe_photo(image_bytes: bytes, recipe_id: int) -> str:
    """Resize/compress an uploaded photo and save it under photos/, named
    by the recipe's stable ID — always a single normalized .jpg file per
    recipe, so uploading a new photo naturally replaces the old one.
    Returns the relative path to store in recipes.photo_path. Raises if
    `image_bytes` isn't a readable image — callers should show that to
    the user rather than swallow it, same as other save-path validation
    in this app.

    If R2 is configured, also uploads the saved file. Unlike an unreadable
    upload, a failed R2 sync doesn't mean the save failed — the local file
    is already written and usable — but it does mean the photo isn't
    durable in production, where local disk doesn't survive a restart
    (see docs/DECISIONS.md — "Phase 3 durability fix"). That distinction
    matters enough to the household to raise `PhotoBackupError` rather
    than swallow it silently like other R2 failures in this module; the
    caller should catch it separately from a generic processing failure
    and still use its `.relative_path`, since the save itself succeeded."""
    PHOTOS_DIR.mkdir(exist_ok=True)
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGB")
    image.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
    relative_path = photo_relative_path(recipe_id)
    local_path = _local_path(relative_path)
    image.save(local_path, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    if _r2_configured() and not _upload_to_r2(local_path, relative_path):
        raise PhotoBackupError(relative_path)
    return relative_path


def delete_recipe_photo(recipe_id: int) -> None:
    """Remove a recipe's photo file, if any (local cache and, if R2 is
    configured, the R2 object too). Safe to call even if no photo exists."""
    relative_path = photo_relative_path(recipe_id)
    _local_path(relative_path).unlink(missing_ok=True)
    if _r2_configured():
        _delete_from_r2(relative_path)


def photo_exists(photo_path: Optional[str]) -> bool:
    """Whether a recipe's stored photo_path actually has a file available
    — guards display code against a stale DB pointer to a removed file.
    Checks the local cache first; if R2 is configured and the file isn't
    cached locally, falls back to asking R2 directly."""
    if not photo_path:
        return False
    if _local_path(photo_path).is_file():
        return True
    if _r2_configured():
        return _r2_object_exists(photo_path)
    return False
