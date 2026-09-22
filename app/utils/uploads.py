"""Validation helpers for untrusted uploaded files."""

from __future__ import annotations

from pathlib import Path


ALLOWED_CERTIFICATE_TYPES = {
    '.jpg': b'\xff\xd8\xff',
    '.jpeg': b'\xff\xd8\xff',
    '.png': b'\x89PNG\r\n\x1a\n',
    '.pdf': b'%PDF-',
}

ALLOWED_PHOTO_TYPES = {
    '.jpg': b'\xff\xd8\xff',
    '.jpeg': b'\xff\xd8\xff',
    '.png': b'\x89PNG\r\n\x1a\n',
    '.webp': b'RIFF',
}

MAX_PHOTO_SIZE_BYTES = 3 * 1024 * 1024  # 3MB


def _match_signature(file_storage, allowed_types: dict, kind: str) -> str:
    """Matches a claimed extension against its file content signature. Shared by all upload validators."""
    filename = str(getattr(file_storage, 'filename', '') or '')
    extension = Path(filename).suffix.lower()
    signature = allowed_types.get(extension)
    if signature is None:
        allowed = ', '.join(sorted(ext.lstrip('.').upper() for ext in allowed_types))
        raise ValueError(f'{kind} must be one of: {allowed}.')

    header = file_storage.stream.read(len(signature))
    file_storage.stream.seek(0)
    if header != signature:
        raise ValueError(f'{kind} content does not match its file type.')
    return extension


def validate_certificate_upload(file_storage) -> str:
    """Returns the safe extension after matching a certificate's claimed type to its content."""
    return _match_signature(file_storage, ALLOWED_CERTIFICATE_TYPES, 'Certificate')


def validate_animal_photo_upload(file_storage) -> str:
    """Returns the safe extension after validating an animal photo's type and size."""
    extension = _match_signature(file_storage, ALLOWED_PHOTO_TYPES, 'Photo')

    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_PHOTO_SIZE_BYTES:
        raise ValueError(f'Photo must be smaller than {MAX_PHOTO_SIZE_BYTES // (1024 * 1024)}MB.')

    return extension
