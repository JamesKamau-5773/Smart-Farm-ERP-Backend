"""Files kept outside the public /uploads tree, served only through authenticated endpoints."""
from __future__ import annotations

import os
from typing import Optional

from flask import current_app

FOLDER = 'private_ledger_attachments'


class PrivateFileStorage:
    @staticmethod
    def _root() -> str:
        # A sibling of UPLOAD_ROOT, so the public /uploads route can never reach it.
        return os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(current_app.config['UPLOAD_ROOT'])), FOLDER))

    @staticmethod
    def save(file_storage, relative_path: str) -> None:
        absolute_path = os.path.join(PrivateFileStorage._root(), relative_path)
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
        file_storage.save(absolute_path)

    @staticmethod
    def resolve(relative_path: str) -> Optional[str]:
        """The file's absolute path, or None if it's missing or would escape the storage folder."""
        root = PrivateFileStorage._root()
        path = os.path.realpath(os.path.join(root, relative_path))
        if not path.startswith(root + os.sep) or not os.path.isfile(path):
            return None
        return path

    @staticmethod
    def delete(relative_path: str) -> None:
        path = PrivateFileStorage.resolve(relative_path)
        if path:
            os.remove(path)
