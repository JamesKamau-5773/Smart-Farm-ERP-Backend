"""What other records refer to an employee, and so must be kept with them."""
from __future__ import annotations

from app.models.hr import Employee
from app.repositories.hr_repo import PayrollRepository
from app.services.advance_ledger_service import AdvanceLedgerService
from app.services.employee_advance_service import EmployeeAdvanceService


class EmployeeHistoryService:
    @staticmethod
    def kinds_on_record(employee: Employee) -> list[str]:
        found = []
        if PayrollRepository.staff_has_payroll(employee.id):
            found.append('payroll')
        if EmployeeAdvanceService.has_history(employee):
            found.append('advances')
        if AdvanceLedgerService.has_entries_for(employee):
            found.append('ledger entries')
        return found
