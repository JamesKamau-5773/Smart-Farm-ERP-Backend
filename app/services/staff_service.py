from app.services.hr_service import HRService


class StaffService(HRService):
    """Compatibility alias for staff-facing naming while employee/payload logic remains in HRService."""

    pass


class SalaryService(HRService):
    """Compatibility alias for payroll-facing naming while HRService remains the canonical implementation."""

    pass
