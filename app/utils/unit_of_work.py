"""One database transaction per use case: commit on success, roll back on any error."""
from __future__ import annotations

from contextlib import contextmanager

from app import db


@contextmanager
def unit_of_work():
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
