"""
AnimalPhotoService — SRP: owns storage, validation, and removal of a Cow's
profile photo. Nothing else (HTTP parsing, DTO shaping) belongs here.
"""

from __future__ import annotations

import os
import uuid

from flask import current_app

from app import db
from app.models.livestock import Cow
from app.utils.uploads import validate_animal_photo_upload


class AnimalPhotoService:
    @staticmethod
    def _tenant_upload_dir(tenant_id: int) -> str:
        upload_dir = os.path.join(current_app.config['UPLOAD_ROOT'], 'animal_photos', f'tenant_{tenant_id}')
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def _delete_existing_file(photo_url: str | None) -> None:
        if not photo_url:
            return
        relative_path = photo_url.split('/uploads/', 1)[-1]
        absolute_path = os.path.join(current_app.config['UPLOAD_ROOT'], relative_path)
        try:
            if os.path.isfile(absolute_path):
                os.remove(absolute_path)
        except OSError:
            current_app.logger.warning('Could not remove stale animal photo file at %s', absolute_path)

    @staticmethod
    def upload_photo(*, tenant_id: int, cow: Cow, file_storage) -> Cow:
        if file_storage is None or not getattr(file_storage, 'filename', None):
            raise ValueError('No photo file was provided.')

        extension = validate_animal_photo_upload(file_storage)

        upload_dir = AnimalPhotoService._tenant_upload_dir(tenant_id)
        stored_filename = f"{cow.id}_{uuid.uuid4().hex}{extension}"
        file_storage.save(os.path.join(upload_dir, stored_filename))

        AnimalPhotoService._delete_existing_file(cow.photo_url)

        cow.photo_url = f"/uploads/animal_photos/tenant_{tenant_id}/{stored_filename}"
        db.session.commit()
        return cow

    @staticmethod
    def remove_photo(*, tenant_id: int, cow: Cow) -> Cow:
        AnimalPhotoService._delete_existing_file(cow.photo_url)
        cow.photo_url = None
        db.session.commit()
        return cow
