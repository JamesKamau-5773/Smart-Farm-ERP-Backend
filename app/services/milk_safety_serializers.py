"""API payloads for milk tests."""
from __future__ import annotations

from app.models.livestock import MilkTest
from app.utils.datetimes import as_utc, iso
from app.utils.user_display import display_name


class MilkTestSerializer:
    @staticmethod
    def serialize(test: MilkTest) -> dict:
        return {
            'id': test.id,
            'cow_id': test.cow_id,
            'tested_at': iso(as_utc(test.tested_at)),
            'test_type': test.test_type,
            'result': test.result,
            'notes': test.notes,
            'recorded_by': test.recorded_by,
            'recorded_by_name': display_name(test.recorded_by),
        }
