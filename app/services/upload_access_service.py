"""Which locally stored uploads a signed-in user may download.

MediaStorage.save_public stores local files as ``<folder>/tenant_<id>/<name>`` (animal
photos, AI certificates). A file is served only to a signed-in user of that tenant;
anything else, including malformed or traversing paths, is answered as not found.
In production these files live on Cloudinary and this route is not used for them.
"""
from __future__ import annotations

from typing import Optional

from app.models.user import User

UPLOAD_FOLDERS = frozenset({'animal_photos', 'ai_certificates'})


class UploadAccessService:
    @staticmethod
    def allowed_path(user: Optional[User], filename: str) -> Optional[str]:
        """The normalised relative path if ``user`` may read it, else None."""
        if user is None or not user.is_active or user.tenant_id is None:
            return None
        raw = str(filename or '')
        if not raw or raw.startswith('/') or '\\' in raw or '\x00' in raw:
            return None
        parts = raw.split('/')
        if any(part in ('', '.', '..') for part in parts) or len(parts) < 3:
            return None
        folder, tenant_folder = parts[0], parts[1]
        if folder not in UPLOAD_FOLDERS or tenant_folder != f'tenant_{user.tenant_id}':
            return None
        return '/'.join(parts)
