"""Upload validation for the uploaded_files app (§14).

Three checks, in this order, applied to every uploaded and every replacing file:
size, extension, and leading bytes. The order is not arbitrary — the size check
is free and rejects the cheapest attack first, and the byte check is last because
it is the only one that has to read the file.

**No third-party library.** ``python-magic`` is the usual choice for this job and
was deliberately not taken: it needs ``libmagic`` present on every developer
machine, on CI, and in every deployment, and it would be the project's first
dependency requiring a system package. What it buys over this module is
recognition of types this app does not accept. Seven extensions, seven
signatures, and a total refusal of anything else is a smaller and more auditable
rule than "whatever libmagic thinks this is".

**What this does not do:** it does not scan for malware, does not validate that a
PDF is well-formed, and does not open an image. A file that starts with ``%PDF-``
and is otherwise garbage passes. This is a *type* check — it stops a renamed
executable, not a malicious document.
"""

from __future__ import annotations

from typing import Any

from uploaded_files.constants import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    SIGNATURE_PREFIX_BYTES,
)
from uploaded_files.exceptions import (
    FileContentMismatchError,
    FileEmptyError,
    FileTooLargeError,
    FileTypeNotAllowedError,
)

#: Extension → the byte prefixes any file of that type must start with.
#:
#: ``docx`` and ``xlsx`` are both ZIP containers and share ``PK\x03\x04``, so
#: this check cannot tell one from the other — the extension decides which of
#: the two it is. That is a known and accepted limit: both are accepted types,
#: so confusing them changes nothing about what is stored or who may read it.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
}

#: WEBP is ``RIFF`` + a four-byte little-endian length + ``WEBP``. The length
#: varies per file, so it cannot be matched as a flat prefix and gets its own
#: two-part rule below.
_WEBP_HEAD = b"RIFF"
_WEBP_TAG = b"WEBP"


def extract_extension(filename: str) -> str:
    """Return the lowercase extension of ``filename`` without its dot.

    Takes the last dot-segment only, so ``passport.pdf.exe`` yields ``exe`` and
    is rejected — a double extension must not be able to smuggle a type past the
    allowlist by putting an accepted one in the middle.
    """
    _, _, extension = (filename or "").rpartition(".")
    return extension.strip().lower()


def assert_size_within_limit(size: int) -> None:
    """Refuse an upload that is larger than ``MAX_UPLOAD_BYTES``, or empty.

    Two distinct exceptions for two opposite problems. Folding the empty case
    into ``FileTooLargeError`` would let a client tell a user that their 0-byte
    file was too big.
    """
    if size > MAX_UPLOAD_BYTES:
        raise FileTooLargeError(f"The file is {size} bytes; the maximum accepted size is {MAX_UPLOAD_BYTES} bytes.")
    if size <= 0:
        # An empty part is a client bug, not an attack, but storing a zero-byte
        # file under a real category would put an unusable record in front of a
        # reviewer with nothing to review.
        raise FileEmptyError("The file is empty.")


def assert_extension_allowed(extension: str) -> str:
    """Refuse an extension outside the allowlist and return its content type.

    Returns the *stored* content type rather than echoing the client's declared
    one, which is advisory on a multipart part and trivially forged.
    """
    content_type = ALLOWED_EXTENSIONS.get(extension)
    if content_type is None:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise FileTypeNotAllowedError(f"'{extension or 'unknown'}' is not an accepted file type. Accepted: {allowed}.")
    return content_type


def assert_content_matches_extension(upload: Any, extension: str) -> None:
    """Refuse a file whose leading bytes disagree with its extension.

    Reads the first few bytes and rewinds, so the caller may still save the file
    afterwards. ``upload`` is a Django ``UploadedFile``; both the in-memory and
    the temporary-file variants support ``read``/``seek``.
    """
    upload.seek(0)
    head = upload.read(SIGNATURE_PREFIX_BYTES)
    upload.seek(0)

    if extension == "webp":
        matched = head.startswith(_WEBP_HEAD) and head[8:12] == _WEBP_TAG
    else:
        matched = any(head.startswith(signature) for signature in _SIGNATURES.get(extension, ()))

    if not matched:
        raise FileContentMismatchError(f"The file's contents do not match its '.{extension}' extension.")


def validate_upload(upload: Any) -> tuple[str, str]:
    """Run all three checks and return ``(original_filename, content_type)``.

    The one entry point services call. Returning the content type here rather
    than deriving it again in the service keeps the allowlist and the stored
    value from ever disagreeing.
    """
    original_filename = (getattr(upload, "name", "") or "").strip()
    extension = extract_extension(original_filename)

    assert_size_within_limit(int(getattr(upload, "size", 0) or 0))
    content_type = assert_extension_allowed(extension)
    assert_content_matches_extension(upload, extension)

    return original_filename, content_type
