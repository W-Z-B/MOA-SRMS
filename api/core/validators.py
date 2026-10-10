"""Upload validation shared by every module that accepts a file from a browser.

Checked before the file reaches storage: extension, declared size and a signature sniff of the first
bytes (so a renamed executable is refused even if the extension is faked). This is a simple allow-list,
not a virus scanner; nothing here replaces serving uploads only through authenticated download endpoints.
"""

from django.core.exceptions import ValidationError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# Signature bytes for the allowed formats. A file must start with one of its extension's signatures.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
}

ALLOWED_EXTENSIONS = tuple(_SIGNATURES)


def validate_upload(uploaded_file, *, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
    """Raise ValidationError unless the file is a reasonably-sized PDF, JPEG or PNG."""
    name = (uploaded_file.name or "").lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    if extension not in _SIGNATURES:
        raise ValidationError(f"Only {', '.join(ALLOWED_EXTENSIONS)} files are accepted.")
    if uploaded_file.size > max_bytes:
        raise ValidationError(f"The file must be smaller than {max_bytes // (1024 * 1024)} MB.")
    head = uploaded_file.read(8)
    uploaded_file.seek(0)
    if not any(head.startswith(sig) for sig in _SIGNATURES[extension]):
        raise ValidationError("The file's contents do not match its extension.")
