"""Shared setup helpers for the uploaded_files test suite.

Every record is built through the owning app's own service, never
``Model.objects.create``, so a fixture goes through the same validation and
audit path a real record does. The actor and owner-record helpers are
re-exported from ``offers.tests.factories`` rather than reimplemented — that
suite already builds the full applicant → journey → catalogue → offer chain this
one needs, and a second copy would drift on the setup every test here depends
on.

**The file bodies below are real, minimal, valid files**, not random bytes with
the right first five characters. That matters for one test in particular: the
content-mismatch check must be able to fail against something that genuinely is
a PNG, or it would only ever be proving that random bytes are not a PDF.
"""

from __future__ import annotations

import io
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from document_history.tests.factories import make_snapshot  # noqa: F401 — re-exported
from documents.tests.factories import make_document  # noqa: F401 — re-exported
from offers.tests.factories import (  # noqa: F401 — re-exported for this suite's tests
    STRONG_PW,
    make_admin,
    make_applicant,
    make_catalogue,
    make_journey,
    make_lead_manager,
    make_manual_offer,
    make_superadmin,
    make_user,
    token_for,
)

from uploaded_files import services
from uploaded_files.constants import FileCategory

# ---------------------------------------------------------------------------
# File bodies
# ---------------------------------------------------------------------------

#: A one-page PDF. Small, but a real file: the header, one object, and %%EOF.
PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)

#: A 1x1 transparent PNG — the full signature, IHDR, IDAT, and IEND.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

#: A minimal JPEG: SOI, APP0/JFIF, EOI.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

#: The leading bytes of any ZIP container, which is what a .docx is.
DOCX_BYTES = b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 24


def pdf_upload(name: str = "passport.pdf", body: bytes | None = None) -> SimpleUploadedFile:
    """A multipart file part carrying a valid PDF."""
    return SimpleUploadedFile(name, body if body is not None else PDF_BYTES, content_type="application/pdf")


def png_upload(name: str = "signature.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def jpeg_upload(name: str = "photo.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, JPEG_BYTES, content_type="image/jpeg")


def mislabelled_upload(name: str = "passport.pdf") -> SimpleUploadedFile:
    """A PNG wearing a ``.pdf`` extension — the content-mismatch case.

    Declares ``application/pdf`` as its content type too, so the test proves the
    check reads the bytes rather than trusting the multipart header.
    """
    return SimpleUploadedFile(name, PNG_BYTES, content_type="application/pdf")


def oversize_upload(name: str = "scan.pdf") -> SimpleUploadedFile:
    """A valid PDF header followed by enough padding to exceed the 10 MB cap."""
    body = PDF_BYTES + b"0" * (10 * 1024 * 1024)
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def disallowed_upload(name: str = "notes.txt") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"plain text", content_type="text/plain")


def empty_upload(name: str = "empty.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"", content_type="application/pdf")


def read_streamed(response: Any) -> bytes:
    """Collect a ``FileResponse``'s streamed bytes."""
    buffer = io.BytesIO()
    for chunk in response.streaming_content:
        buffer.write(chunk)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def upload_for_applicant(actor: Any, applicant: Any, **overrides: Any) -> Any:
    """One stored file owned by an applicant — the common case."""
    upload = overrides.pop("upload", None) or pdf_upload()
    data: dict[str, Any] = {
        "applicant": applicant.id,
        "category": FileCategory.PASSPORT,
        **overrides,
    }
    return services.upload_file(actor=actor, upload=upload, data=data)


def upload_for(actor: Any, owner_field: str, owner: Any, **overrides: Any) -> Any:
    """One stored file owned by any of the five record types."""
    upload = overrides.pop("upload", None) or pdf_upload()
    data: dict[str, Any] = {
        owner_field: owner.id,
        "category": overrides.pop("category", FileCategory.OTHER),
        **overrides,
    }
    return services.upload_file(actor=actor, upload=upload, data=data)


def make_signatory(actor: Any, **overrides: Any) -> Any:
    """A signatory, re-exported by call rather than by import.

    ``document_templates.tests.factories`` imports the upload part builders from
    this module at module level. A module-level re-export in this direction as
    well would close a cycle, and ``png_upload`` is defined below this module's
    import block — so whichever module loaded second would fail with "cannot
    import name … from partially initialized module". Deferring to call time
    keeps both suites able to reach each other.
    """
    from document_templates.tests.factories import make_signatory as _make_signatory

    return _make_signatory(actor, **overrides)
