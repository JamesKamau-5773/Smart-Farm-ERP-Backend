"""Serves previously uploaded files (animal photos, AI certificates) from configured storage."""

from __future__ import annotations

from flask import Blueprint, current_app, send_from_directory

uploads_bp = Blueprint('uploads', __name__)


@uploads_bp.route('/uploads/<path:filename>', methods=['GET'])
def serve_upload(filename):
    return send_from_directory(current_app.config['UPLOAD_ROOT'], filename)
