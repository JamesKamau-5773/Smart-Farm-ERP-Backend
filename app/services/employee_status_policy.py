"""An employee's working status, and when a leave becomes overdue."""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

VALID_STATUSES = frozenset({'ACTIVE', 'ON_LEAVE', 'OVERDUE', 'INACTIVE'})


class EmployeeStatusPolicy:
    @staticmethod
    def normalize(value: Optional[str]) -> str:
        if not value:
            return 'ACTIVE'
        normalized = str(value).strip().upper()
        if normalized not in VALID_STATUSES:
            raise ValueError('status must be one of ACTIVE, ON_LEAVE, OVERDUE, or INACTIVE.')
        return normalized

    @staticmethod
    def current_status(employee) -> str:
        status = (employee.status or 'ACTIVE').upper()
        if status == 'ON_LEAVE' and employee.expected_return_date and not employee.actual_return_date:
            if employee.expected_return_date < date.today():
                return 'OVERDUE'
        return status

    @staticmethod
    def synchronize(employees: Iterable) -> bool:
        """Stores each employee's current status; True when any changed. The caller commits."""
        changed = False
        for employee in employees:
            status = EmployeeStatusPolicy.current_status(employee)
            if employee.status != status:
                employee.status = status
                changed = True
        return changed
