"""Unit tests: upload validation and the reviewed-source URL allow-list."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.knowledge import service as knowledge  # noqa: E402
from app.services import imports as import_service  # noqa: E402
from app.services.errors import ImportFailedError  # noqa: E402


def _png(size=(64, 64), color="white") -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_with_exif() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (64, 64), "white")
    exif = image.getexif()
    exif[0x010F] = "DemoCamera"  # Make
    exif[0x0110] = "DemoModel"  # Model
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_real_png_is_accepted_and_reencoded():
    mime, fmt, clean = import_service.validate_upload(
        _png(), filename="ok.png", declared_mime="image/png", settings=Settings()
    )
    assert (mime, fmt) == ("image/png", "PNG")
    assert clean


def test_extension_spoofing_is_rejected():
    with pytest.raises(ImportFailedError):
        import_service.validate_upload(
            _png(), filename="not-really.jpg", declared_mime="image/jpeg", settings=Settings()
        )


def test_non_image_bytes_are_rejected():
    with pytest.raises(ImportFailedError):
        import_service.validate_upload(
            b"<html>not an image</html>", filename="page.png", declared_mime="image/png", settings=Settings()
        )


def test_path_traversal_in_filename_is_rejected():
    with pytest.raises(ImportFailedError):
        import_service.validate_upload(
            _png(), filename="../../etc/passwd.png", declared_mime="image/png", settings=Settings()
        )


def test_oversized_pixel_buffer_is_rejected():
    settings = Settings(MAX_UPLOAD_PIXELS=100)
    with pytest.raises(ImportFailedError):
        import_service.validate_upload(
            _png(size=(64, 64)), filename="big.png", declared_mime="image/png", settings=settings
        )


def test_oversized_file_is_rejected():
    settings = Settings(MAX_UPLOAD_MB=0)
    with pytest.raises(ImportFailedError):
        import_service.validate_upload(
            _png(), filename="big.png", declared_mime="image/png", settings=settings
        )


def test_unsupported_content_type_is_rejected():
    with pytest.raises(ImportFailedError):
        import_service.validate_upload(
            _png(), filename="ok.png", declared_mime="application/pdf", settings=Settings()
        )


def test_exif_metadata_is_stripped():
    from PIL import Image

    original = _jpeg_with_exif()
    assert b"DemoCamera" in original or b"DemoModel" in original
    _mime, _fmt, clean = import_service.validate_upload(
        original, filename="photo.jpg", declared_mime="image/jpeg", settings=Settings()
    )
    assert b"DemoCamera" not in clean
    assert b"DemoModel" not in clean
    with Image.open(io.BytesIO(clean)) as reopened:
        assert dict(reopened.getexif()) == {}


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://pubchem.ncbi.nlm.nih.gov/compound/936", True),
        ("http://www.cerave.com/skincare", True),
        ("https://www.cerave.com/skincare/moisturizers/moisturizing-cream", True),
        ("https://api.open-meteo.com/v1/forecast", True),  # subdomains of an allowed domain
        ("https://open-meteo.com.evil.invalid/", False),  # suffix spoofing must fail
        ("https://evil.example.invalid/track", False),
        ("file:///etc/passwd", False),
        ("demo://chengquan/D01/instructions-v1", True),
        ("local://fixtures/a", True),
        (None, True),
    ],
)
def test_reviewed_source_url_allow_list(url, allowed):
    ok, reason = knowledge.source_url_allowed(url, Settings().allowed_domain_list)
    assert ok is allowed, reason


def test_seeded_real_sources_pass_the_allow_list(app_settings, db):
    from sqlalchemy import select

    from app.models import KnowledgeSource

    rows = list(db.execute(select(KnowledgeSource)).scalars())
    assert rows
    for source in rows:
        ok, reason = knowledge.source_url_allowed(source.url, app_settings.allowed_domain_list)
        assert ok, f"{source.title}: {reason}"
