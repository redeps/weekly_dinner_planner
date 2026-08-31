"""
Milestone 11 tests: recipe photo storage (services/photos.py).

PHOTOS_DIR is monkeypatched to an isolated temp directory for every test
— never touches the real photos/ directory.
"""

import io

import pytest
from PIL import Image

from services import photos


@pytest.fixture(autouse=True)
def isolated_photos_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "PHOTOS_DIR", tmp_path / "photos")


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
