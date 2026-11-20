"""Closes a staff member's access to the farm: login, sessions and any pending invite."""
from __future__ import annotations

from app.models.hr import Employee, EmployeeOnboardingStatus
from app.services.session_service import SessionService


class StaffAccessService:
    @staticmethod
    def revoke(employee: Employee) -> None:
        """Stages the change; the caller commits."""
        employee.onboarding_status = EmployeeOnboardingStatus.DISABLED
        employee.onboarding_invite_nonce = None
        employee.onboarding_invite_expires_at = None
        if employee.user is not None:
            employee.user.is_active = False
            SessionService.revoke_all_sessions(employee.user)
