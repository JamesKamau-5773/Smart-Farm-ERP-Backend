"""Residue and quality tests on a cow's milk. A failed test puts the milk on hold."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.livestock import Cow, MilkTest, MilkTestResult
from app.repositories.milk_test_repo import MilkTestRepository
from app.services.milk_hold_service import MilkHoldService, require_cow
from app.utils.api_errors import ApiError
from app.utils.datetimes import parse_iso_datetime
from app.utils.unit_of_work import unit_of_work

MAX_TEST_TYPE_LENGTH = 60
# Allows for a phone clock that runs a little fast.
CLOCK_SKEW = timedelta(minutes=5)


class MilkTestService:
    @staticmethod
    def record(tenant_id: int, data: dict, *, actor_id: Optional[int], ip_address=None) -> tuple[MilkTest, Cow, bool]:
        """Returns the test, the cow and whether the test put her milk on hold."""
        cow = require_cow(tenant_id, data.get('cow_id'))
        result = str(data.get('result') or '').strip().upper()
        if result not in MilkTestResult.ALL:
            raise ApiError('VALIDATION_ERROR', 'result must be PASS or FAIL.')
        test_type = str(data.get('test_type') or '').strip()
        if not test_type or len(test_type) > MAX_TEST_TYPE_LENGTH:
            raise ApiError('VALIDATION_ERROR', f'test_type is required (at most {MAX_TEST_TYPE_LENGTH} characters), e.g. "Antibiotic residue".')
        try:
            tested_at = parse_iso_datetime(data.get('tested_at')) or datetime.now(timezone.utc)
        except ValueError:
            raise ApiError('VALIDATION_ERROR', 'tested_at must be an ISO 8601 date-time.')
        if tested_at > datetime.now(timezone.utc) + CLOCK_SKEW:
            raise ApiError('VALIDATION_ERROR', 'tested_at cannot be in the future.')

        notes = (data.get('notes') or '').strip() or None
        failed = result == MilkTestResult.FAIL
        with unit_of_work():
            test = MilkTestRepository.stage(MilkTest(
                tenant_id=tenant_id, cow_id=cow.id, tested_at=tested_at, test_type=test_type,
                result=result, notes=notes, recorded_by=actor_id,
            ))
            if failed:
                MilkHoldService.stage(cow, f'Failed {test_type} test', notes=notes, actor_id=actor_id, ip_address=ip_address)
        return test, cow, failed

    @staticmethod
    def list_for_cow(tenant_id: int, cow_id) -> list[MilkTest]:
        cow = require_cow(tenant_id, cow_id)
        return MilkTestRepository.list_for_cow(cow.id, tenant_id)
