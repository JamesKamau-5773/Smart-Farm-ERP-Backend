"""
AnimalPhotoService — SRP: owns storage, validation, and removal of a Cow's
profile photo. Nothing else (HTTP parsing, DTO shaping) belongs here.
"""

from __future__ import annotations

import uuid

from app import db
from app.models.livestock import Cow
from app.services.media_storage import MediaStorage
from app.utils.uploads import validate_animal_photo_upload


class AnimalPhotoService:
    @staticmethod
    def upload_photo(*, tenant_id: int, cow: Cow, file_storage) -> Cow:
        if file_storage is None or not getattr(file_storage, 'filename', None):
            raise ValueError('No photo file was provided.')

        extension = validate_animal_photo_upload(file_storage)

        # Public: Cloudinary in production, UPLOAD_ROOT locally (MediaStorage).
        photo_url = MediaStorage.save_public(
            file_storage,
            folder=f'animal_photos/tenant_{tenant_id}',
            name=f'{cow.id}_{uuid.uuid4().hex}',
            extension=extension,
        )
        MediaStorage.delete_public(cow.photo_url)

        cow.photo_url = photo_url
        db.session.commit()
        return cow

    @staticmethod
    def remove_photo(*, tenant_id: int, cow: Cow) -> Cow:
        MediaStorage.delete_public(cow.photo_url)
        cow.photo_url = None
        db.session.commit()
        return cow
