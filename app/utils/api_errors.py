"""Typed errors that services raise and a global handler renders.

The response is the ``{"code": ..., "error": ...}`` envelope, plus any extra
fields the caller needs (for example ``loan_balance`` on ``LOAN_OUTSTANDING``).
"""
from __future__ import annotations

from flask import jsonify


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def to_response(self):
        return jsonify({'code': self.code, 'error': self.message, **self.extra}), self.status
