"""Payslip PDFs for a finalized payroll run."""
from __future__ import annotations

from app.models.hr import PayrollRunStatus
from app.repositories.hr_repo import EmployeeRepository, PayrollRepository
from app.repositories.tenant_repo import TenantRepository
from app.services.payroll_run_service import PayrollRunService
from app.services.payslip_view import PayslipView
from app.services.pdf_renderer import PdfRenderer
from app.utils.api_errors import ApiError

TEMPLATE = 'pdf/payslip.html'


class PayslipService:
    @staticmethod
    def render(tenant_id: int, run_id: str, staff_id: int) -> tuple[bytes, str]:
        """Returns the PDF and a download filename."""
        run = PayrollRunService.find(tenant_id, run_id)
        if run.status == PayrollRunStatus.DRAFT:
            raise ApiError('PAYROLL_NOT_FINALIZED', 'Payslips are available once the payroll run is finalized.', 409)
        item = PayrollRepository.get_line_item(run_id=run.id, staff_id=staff_id)
        if item is None:
            raise ApiError('NOT_FOUND', 'This employee is not on that payroll run.', 404)

        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        tenant = TenantRepository.get_by_id(tenant_id)
        slip = PayslipView.build(
            run, item,
            employer_name=tenant.name if tenant else '',
            role=employee.role if employee else None,
            id_number=employee.id_number if employee else None,
        )
        filename = f'payslip-{run.payroll_year:04d}-{run.payroll_month:02d}-{staff_id}.pdf'
        return PdfRenderer.render(TEMPLATE, slip=slip), filename
