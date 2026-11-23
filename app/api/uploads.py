"""Serves locally stored uploads (animal photos, AI certificates) to signed-in users of the owning tenant.

The access rule lives in app/services/upload_access_service.py. Browsers send the
session cookie with <img> requests to the API on the same site, so images keep working.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, send_from_directory
from flask_jwt_extended import jwt_required

from app.services.upload_access_service import UploadAccessService
from app.utils.current_user import require_current_user

uploads_bp = Blueprint('uploads', __name__)


@uploads_bp.route('/uploads/<path:filename>', methods=['GET'])
@jwt_required()
def serve_upload(filename):
    path = UploadAccessService.allowed_path(require_current_user(), filename)
    if path is None:
        abort(404)
    response = send_from_directory(current_app.config['UPLOAD_ROOT'], path)
    # Per-user content: never stored by shared caches.
    response.headers['Cache-Control'] = 'private, max-age=300'
    return response
