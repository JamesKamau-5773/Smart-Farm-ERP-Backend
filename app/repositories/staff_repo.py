from app.repositories.hr_repo import EmployeeRepository, PayrollRepository


class StaffRepository(EmployeeRepository):
    """Compatibility alias for staff-facing naming while employees remain the stored entity."""

    pass


class SalaryRepository(PayrollRepository):
    """Compatibility alias for payroll data access using staff-facing terminology."""

    pass