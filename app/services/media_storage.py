"""Where uploaded files live: Cloudinary in production, the local UPLOAD_ROOT otherwise.

``MEDIA_STORAGE`` (config.py) picks the place: 'cloudinary' when CLOUDINARY_URL is set (as on
Render, whose own disk is wiped on every deploy), 'local' otherwise (development and tests).

Two kinds of file:

* **public** (cow photos, AI certificates): anyone with the link may see them. What is stored in
  the database is the link itself: Cloudinary's ``https://res.cloudinary.com/...`` URL, or
  ``/uploads/...`` on local disk (served by app/api/uploads.py).
* **private** (receipt photos on ledger entries): only the backend reads them, for the farm's
  signed-in users. What is stored is a key: ``cloudinary:<resource_type>/<format>/<public_id>``
  for an *authenticated* Cloudinary asset (no public link exists), or a path under the private
  folder on local disk (PrivateFileStorage).

Rows saved before the switch keep their local values and keep working while those files exist;
scripts/move_uploads_to_cloudinary.py moves them.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Optional, Union

import requests
from flask import current_app

from app.services.private_file_storage import PrivateFileStorage

CLOUDINARY_KEY_PREFIX = 'cloudinary:'
_CLOUDINARY_HOST = 'res.cloudinary.com'
_DOWNLOAD_TIMEOUT_SECONDS = 20

# What can be uploaded: a werkzeug FileStorage from a request, or a path to a file on disk
# (the migration script).
Source = Union[str, os.PathLike, object]


class MediaStorageError(RuntimeError):
    """Storage is misconfigured or the provider refused the file."""


def uses_cloudinary() -> bool:
    return current_app.config.get('MEDIA_STORAGE') == 'cloudinary'


def _cloudinary():
    """The configured SDK. Credentials come from CLOUDINARY_URL, never from code."""
    import cloudinary
    import cloudinary.uploader  # noqa: F401  (registers cloudinary.uploader)
    import cloudinary.utils  # noqa: F401

    url = current_app.config.get('CLOUDINARY_URL') or ''
    parsed = urllib.parse.urlsplit(url)
    cloud_name = parsed.netloc.rsplit('@', 1)[-1]
    if parsed.scheme != 'cloudinary' or not cloud_name or not parsed.username or not parsed.password:
        raise MediaStorageError('MEDIA_STORAGE is cloudinary but CLOUDINARY_URL is missing or malformed.')
    if any(mark in url for mark in '<>') or 'your_api' in url.lower():
        # Cloudinary's example value (cloudinary://<your_api_key>:<your_api_secret>@...) pasted as is.
        raise MediaStorageError(
            'CLOUDINARY_URL still holds the example placeholders; paste the real "API environment '
            'variable" from the Cloudinary console (Settings > API Keys).'
        )
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=urllib.parse.unquote(parsed.username),
        api_secret=urllib.parse.unquote(parsed.password),
        secure=True,
    )
    return cloudinary


def _folder(*parts: str) -> str:
    return '/'.join(part.strip('/') for part in (current_app.config.get('CLOUDINARY_FOLDER') or 'maziwa', *parts) if part)


def _upload_source(source: Source):
    """What the SDK accepts: a path as a string, or the request file's stream (rewound)."""
    if isinstance(source, (str, os.PathLike)):
        return os.fspath(source)
    stream = getattr(source, 'stream', source)
    if hasattr(stream, 'seek'):
        stream.seek(0)
    return stream


def _upload(source: Source, *, folder: str, name: str, delivery_type: str) -> dict:
    cloudinary = _cloudinary()
    try:
        return cloudinary.uploader.upload(
            _upload_source(source),
            folder=_folder(folder),
            public_id=name,
            resource_type='auto',
            type=delivery_type,
            overwrite=False,
            unique_filename=False,
            use_filename=False,
        )
    except Exception as exc:  # the SDK raises its own Error types; callers see one
        raise MediaStorageError(f'Cloudinary upload failed: {exc}') from exc


def _save_local(source: Source, absolute_path: str) -> None:
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    if isinstance(source, (str, os.PathLike)):
        with open(source, 'rb') as reader, open(absolute_path, 'wb') as writer:
            writer.write(reader.read())
    else:
        source.save(absolute_path)


def cloudinary_public_id_from_url(url: str) -> Optional[tuple[str, str, str]]:
    """``(public_id, resource_type, delivery_type)`` for a link to this account's Cloudinary
    files, or None for any other link.

    ``https://res.cloudinary.com/<cloud>/<resource_type>/<type>/[<transformations>/][v<n>/]<public_id>[.<ext>]``
    The extension is part of the public id only for raw files.
    """
    parts = urllib.parse.urlsplit(url or '')
    if parts.netloc != _CLOUDINARY_HOST:
        return None
    segments = [segment for segment in parts.path.split('/') if segment]
    if len(segments) < 4:
        return None
    cloud, resource_type, delivery_type, *rest = segments
    try:
        expected_cloud = urllib.parse.urlsplit(current_app.config.get('CLOUDINARY_URL') or '').netloc.rsplit('@', 1)[-1]
    except ValueError:
        expected_cloud = ''
    if expected_cloud and cloud != expected_cloud:
        return None
    version_at = next((i for i, segment in enumerate(rest) if segment[:1] == 'v' and segment[1:].isdigit()), None)
    if version_at is not None:
        rest = rest[version_at + 1:]
    if not rest:
        return None
    public_id = '/'.join(rest)
    if resource_type != 'raw':
        public_id = os.path.splitext(public_id)[0]
    return public_id, resource_type, delivery_type


class MediaStorage:
    # -- public files ---------------------------------------------------------------------
    @staticmethod
    def save_public(source: Source, *, folder: str, name: str, extension: str) -> str:
        """Saves a file anyone with the link may see; returns the link to store."""
        if uses_cloudinary():
            return _upload(source, folder=folder, name=name, delivery_type='upload')['secure_url']
        relative = f'{folder.strip("/")}/{name}{extension}'
        _save_local(source, os.path.join(current_app.config['UPLOAD_ROOT'], relative))
        return f'/uploads/{relative}'

    @staticmethod
    def delete_public(url: Optional[str]) -> None:
        """Removes a public file by its stored link. Never raises: a stale file must not block a save."""
        if not url:
            return
        try:
            if url.startswith('/uploads/'):
                root = os.path.realpath(current_app.config['UPLOAD_ROOT'])
                path = os.path.realpath(os.path.join(root, url.split('/uploads/', 1)[1]))
                if path.startswith(root + os.sep) and os.path.isfile(path):
                    os.remove(path)
                return
            identity = cloudinary_public_id_from_url(url)
            if identity and uses_cloudinary():
                public_id, resource_type, delivery_type = identity
                _cloudinary().uploader.destroy(public_id, resource_type=resource_type, type=delivery_type, invalidate=True)
        except Exception:
            current_app.logger.warning('Could not remove the old file at %s', url, exc_info=True)

    # -- private files ----------------------------------------------------------------------
    @staticmethod
    def save_private(source: Source, *, folder: str, name: str, extension: str) -> str:
        """Saves a file only the backend may read; returns the key to store."""
        if uses_cloudinary():
            result = _upload(source, folder=f'private/{folder}', name=name, delivery_type='authenticated')
            file_format = result.get('format') or extension.lstrip('.')
            return f"{CLOUDINARY_KEY_PREFIX}{result['resource_type']}/{file_format}/{result['public_id']}"
        relative = os.path.join(folder, f'{name}{extension}')
        if isinstance(source, (str, os.PathLike)):
            _save_local(source, os.path.join(PrivateFileStorage._root(), relative))
        else:
            PrivateFileStorage.save(source, relative)
        return relative

    @staticmethod
    def read_private(key: str) -> Optional[bytes]:
        """The file's bytes, or None if it is missing. Cloudinary files are fetched with a signed link."""
        if key.startswith(CLOUDINARY_KEY_PREFIX):
            resource_type, file_format, public_id = key[len(CLOUDINARY_KEY_PREFIX):].split('/', 2)
            url, _options = _cloudinary().utils.cloudinary_url(
                public_id, resource_type=resource_type, type='authenticated', format=file_format,
                sign_url=True, secure=True,
            )
            try:
                response = requests.get(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
            except requests.RequestException:
                current_app.logger.warning('Could not fetch the private file %s from Cloudinary.', public_id, exc_info=True)
                return None
            return response.content if response.status_code == 200 else None
        path = PrivateFileStorage.resolve(key)
        if path is None:
            return None
        with open(path, 'rb') as handle:
            return handle.read()

    @staticmethod
    def delete_private(key: Optional[str]) -> None:
        """Removes a private file by its key. Never raises."""
        if not key:
            return
        try:
            if key.startswith(CLOUDINARY_KEY_PREFIX):
                resource_type, _format, public_id = key[len(CLOUDINARY_KEY_PREFIX):].split('/', 2)
                _cloudinary().uploader.destroy(public_id, resource_type=resource_type, type='authenticated', invalidate=True)
            else:
                PrivateFileStorage.delete(key)
        except Exception:
            current_app.logger.warning('Could not remove the private file %s', key, exc_info=True)
