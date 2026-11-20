"""Guarantees the {"code", "error"} error envelope on a blueprint's responses.

Handlers that set a specific code keep it; plain {"error": ...} responses get a
code derived from the HTTP status, so clients can branch on `code` everywhere.
"""
from __future__ import annotations

from flask import json

STATUS_CODES = {
    400: 'VALIDATION_ERROR',
    401: 'UNAUTHENTICATED',
    403: 'FORBIDDEN',
    404: 'NOT_FOUND',
    409: 'CONFLICT',
    422: 'UNPROCESSABLE',
    429: 'RATE_LIMITED',
}


def ensure_error_code(response):
    if response.status_code < 400 or not response.is_json:
        return response
    body = response.get_json(silent=True)
    if not isinstance(body, dict) or 'code' in body or 'error' not in body:
        return response
    body['code'] = STATUS_CODES.get(response.status_code, 'INTERNAL_ERROR' if response.status_code >= 500 else 'ERROR')
    response.set_data(json.dumps(body))
    return response


def register_error_envelope(*blueprints) -> None:
    for blueprint in blueprints:
        blueprint.after_request(ensure_error_code)
