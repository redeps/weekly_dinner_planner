"""
Milestone 11 tests: recipe photo storage (services/photos.py).

PHOTOS_DIR is monkeypatched to an isolated temp directory for every test
— never touches the real photos/ directory.

Milestone 13 Phase 3 (R2) tests below use `moto` to mock the S3 API
`boto3` speaks, swapped in via `photos._r2_client` rather than a real R2
endpoint — moto doesn't intercept requests aimed at a custom (non-AWS)
`endpoint_url` (verified directly: it attempts a real network connection
and fails with an SSL error), so the mocked client is built with only
`region_name` set, exercising the exact same boto3 API calls
`_r2_client()` would make against a real R2 endpoint. See
docs/DECISIONS.md — Milestone 13 Phase 3.
"""

import io

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from services import photos

R2_TEST_BUCKET = "meal-planner-photos-test"


@pytest.fixture(autouse=True)
def isolated_photos_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTOS_DIR", tmp_path / "photos")


@pytest.fixture
def r2_client():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=R2_TEST_BUCKET)
        yield client


@pytest.fixture
def r2_configured(monkeypatch, r2_client):
    """Simulates st.secrets["r2"] being configured and reachable."""
    monkeypatch.setattr(photos, "_r2_configured", lambda: True)
    monkeypatch.setattr(photos, "_r2_client", lambda: r2_client)
    monkeypatch.setattr(photos, "_r2_bucket", lambda: R2_TEST_BUCKET)
    return r2_client


@pytest.fixture
def r2_configured_but_broken(monkeypatch):
    """Simulates st.secrets["r2"] being present (so the app believes R2 is
    the active backend) but every call to it failing — bad credentials,
    network unreachable, wrong bucket, etc. Distinguished from R2 simply
    not being configured at all, which the other 13 tests above already
    cover (this repo's real .streamlit/secrets.toml has no [r2] section)."""
    monkeypatch.setattr(photos, "_r2_configured", lambda: True)

    def _raise_client():
        raise RuntimeError("simulated R2 unreachable")

    monkeypatch.setattr(photos, "_r2_client", _raise_client)


def make_image_bytes(*, size=(100, 100), mode="RGB", fmt="JPEG"):
    image = Image.new(mode, size, color=(200, 50, 50) if mode == "RGB" else (200, 50, 50, 128))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_photo_relative_path_format():
    assert photos.photo_relative_path(42) == "photos/42.jpg"


def test_save_recipe_photo_creates_file_and_returns_relative_path():
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=7)
    assert relative_path == "photos/7.jpg"
    assert photos.resolve_photo_path(relative_path).is_file()


def test_save_recipe_photo_resizes_large_image():
    big_bytes = make_image_bytes(size=(3000, 1500))
    relative_path = photos.save_recipe_photo(big_bytes, recipe_id=1)
    with Image.open(photos.resolve_photo_path(relative_path)) as saved:
        assert max(saved.size) <= photos._MAX_DIMENSION


def test_save_recipe_photo_does_not_upscale_small_image():
    small_bytes = make_image_bytes(size=(50, 40))
    relative_path = photos.save_recipe_photo(small_bytes, recipe_id=2)
    with Image.open(photos.resolve_photo_path(relative_path)) as saved:
        assert saved.size == (50, 40)


def test_save_recipe_photo_converts_rgba_png_to_rgb_jpeg():
    rgba_bytes = make_image_bytes(mode="RGBA", fmt="PNG")
    relative_path = photos.save_recipe_photo(rgba_bytes, recipe_id=3)
    with Image.open(photos.resolve_photo_path(relative_path)) as saved:
        assert saved.mode == "RGB"
        assert saved.format == "JPEG"


def test_save_recipe_photo_overwrites_existing_photo_for_same_recipe():
    first_path = photos.save_recipe_photo(make_image_bytes(size=(100, 100)), recipe_id=5)
    second_path = photos.save_recipe_photo(make_image_bytes(size=(200, 200)), recipe_id=5)
    assert first_path == second_path
    matching_files = list(photos.PHOTOS_DIR.glob("5.*"))
    assert len(matching_files) == 1
    with Image.open(photos.resolve_photo_path(second_path)) as saved:
        assert saved.size == (200, 200)


def test_save_recipe_photo_raises_for_invalid_image_bytes():
    with pytest.raises(Exception):
        photos.save_recipe_photo(b"not an image", recipe_id=9)


def test_delete_recipe_photo_removes_file():
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=4)
    assert photos.resolve_photo_path(relative_path).is_file()
    photos.delete_recipe_photo(4)
    assert not photos.resolve_photo_path(relative_path).is_file()


def test_delete_recipe_photo_safe_when_no_file_exists():
    photos.delete_recipe_photo(999)  # must not raise


def test_photo_exists_true_when_file_present():
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=6)
    assert photos.photo_exists(relative_path) is True


def test_photo_exists_false_for_none():
    assert photos.photo_exists(None) is False


def test_photo_exists_false_for_empty_string():
    assert photos.photo_exists("") is False


def test_photo_exists_false_when_file_missing_despite_path_set():
    assert photos.photo_exists("photos/does-not-exist.jpg") is False


# --- R2 (Milestone 13 Phase 3): upload ---


def test_save_recipe_photo_uploads_to_r2_when_configured(r2_configured):
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=10)
    obj = r2_configured.get_object(Bucket=R2_TEST_BUCKET, Key=relative_path)
    assert obj["Body"].read() == photos.resolve_photo_path(relative_path).read_bytes()
    assert obj["ContentType"] == "image/jpeg"


def test_save_recipe_photo_still_writes_local_cache_when_r2_configured(r2_configured):
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=11)
    assert photos._local_path(relative_path).is_file()


# --- R2: fetch (cache-miss download, and existence check) ---


def test_resolve_photo_path_downloads_from_r2_on_cache_miss(r2_configured):
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=12)
    original_bytes = photos._local_path(relative_path).read_bytes()

    # Simulate a deployed app's ephemeral disk losing the local cache —
    # the R2 upload above is unaffected.
    photos._local_path(relative_path).unlink()
    assert not photos._local_path(relative_path).is_file()

    resolved = photos.resolve_photo_path(relative_path)
    assert resolved.is_file()
    assert resolved.read_bytes() == original_bytes


def test_photo_exists_true_via_r2_when_not_cached_locally(r2_configured):
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=13)
    photos._local_path(relative_path).unlink()
    assert photos.photo_exists(relative_path) is True


def test_photo_exists_false_when_r2_configured_and_object_never_uploaded(r2_configured):
    assert photos.photo_exists("photos/999.jpg") is False


# --- R2: delete ---


def test_delete_recipe_photo_removes_from_r2(r2_configured):
    relative_path = photos.save_recipe_photo(make_image_bytes(), recipe_id=14)
    photos.delete_recipe_photo(14)
    assert photos._r2_object_exists(relative_path) is False


# --- R2: graceful degradation when configured but unreachable/failing ---


def test_save_recipe_photo_local_save_still_succeeds_when_r2_upload_fails(r2_configured_but_broken):
    # A failed R2 sync raises PhotoBackupError (Milestone 13 Phase 3
    # durability fix — see docs/DECISIONS.md), distinct from a genuine
    # local processing failure, but the local file must already be saved
    # and usable regardless — the caller still gets .relative_path off
    # the exception to record in recipes.photo_path.
    with pytest.raises(photos.PhotoBackupError) as exc_info:
        photos.save_recipe_photo(make_image_bytes(), recipe_id=15)
    relative_path = exc_info.value.relative_path
    assert relative_path == "photos/15.jpg"
    assert photos._local_path(relative_path).is_file()


def test_resolve_photo_path_does_not_raise_when_r2_download_fails(r2_configured_but_broken):
    # No local cache and R2 unreachable: must return a Path, never raise —
    # the caller (photo_exists, checked first at every real call site)
    # would already have reported this photo as unavailable.
    resolved = photos.resolve_photo_path("photos/16.jpg")
    assert not resolved.is_file()


def test_photo_exists_false_when_r2_configured_but_unreachable(r2_configured_but_broken):
    assert photos.photo_exists("photos/17.jpg") is False


def test_delete_recipe_photo_does_not_raise_when_r2_delete_fails(r2_configured_but_broken):
    with pytest.raises(photos.PhotoBackupError):
        photos.save_recipe_photo(make_image_bytes(), recipe_id=18)  # local file still written
    photos.delete_recipe_photo(18)  # must not raise despite the broken R2 client
    assert not photos._local_path(photos.photo_relative_path(18)).is_file()


# --- R2: backend selection itself ---


def test_r2_not_configured_by_default():
    # This repo's real .streamlit/secrets.toml has no [r2] section — every
    # test above this point in the file that didn't use r2_configured /
    # r2_configured_but_broken ran against that real config with no
    # monkeypatching at all, which is itself the primary "R2 absent"
    # coverage. This test just pins down _r2_configured()'s own behavior
    # against that same real, unconfigured state directly.
    assert photos._r2_configured() is False
