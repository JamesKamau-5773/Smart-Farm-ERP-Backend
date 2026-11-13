from decimal import Decimal

from app.models.finance import CostClass, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.repositories.ledger_repo import TransactionRepository
from app.models.hr import EMPLOYEE_STATUTORY_FIELDS, EMPLOYER_STATUTORY_FIELDS


class PayrollLedgerService:
    """Posts a finalized payroll run to the ledger.

    Two entries, each idempotent by reference code: net wages paid to staff,
    and statutory amounts remitted to KRA, NSSF and SHA (employee deductions
    plus the employer's NSSF and Housing Levy contributions).
    """

    @staticmethod
    def reference_code(payroll_run):
        return f'PAYROLL-{payroll_run.payroll_year:04d}-{payroll_run.payroll_month:02d}'

    @staticmethod
    def statutory_reference_code(payroll_run):
        return f'{PayrollLedgerService.reference_code(payroll_run)}-STATUTORY'

    @staticmethod
    def statutory_total(payroll_run) -> Decimal:
        fields = EMPLOYEE_STATUTORY_FIELDS + EMPLOYER_STATUTORY_FIELDS
        return sum(
            (Decimal(str(getattr(item, field) or 0)) for item in payroll_run.line_items for field in fields),
            Decimal('0'),
        )

    @staticmethod
    def post_expense(payroll_run, *, actor_id=None):
        period = f'{payroll_run.payroll_year:04d}-{payroll_run.payroll_month:02d}'
        wages = PayrollLedgerService._post(
            payroll_run,
            reference_code=PayrollLedgerService.reference_code(payroll_run),
            amount=Decimal(str(payroll_run.total_net_pay or 0)),
            item_name='Monthly payroll',
            description=f'Payroll for {period}',
            counterparty_name='Employees',
            actor_id=actor_id,
        )
        PayrollLedgerService._post(
            payroll_run,
            reference_code=PayrollLedgerService.statutory_reference_code(payroll_run),
            amount=PayrollLedgerService.statutory_total(payroll_run),
            item_name='Payroll statutory deductions',
            description=f'PAYE, NSSF, SHIF and Housing Levy for {period} (employee and employer)',
            counterparty_name='KRA / NSSF / SHA',
            actor_id=actor_id,
        )
        return wages

    @staticmethod
    def _post(payroll_run, *, reference_code, amount, item_name, description, counterparty_name, actor_id):
        existing = TransactionRepository.get_by_reference(payroll_run.tenant_id, reference_code)
        if existing:
            return existing
        if amount <= 0:
            return None

        actor_id = int(actor_id) if actor_id is not None else None
        return TransactionRepository.stage(Transaction(
            tenant_id=payroll_run.tenant_id,
            farm_id=payroll_run.farm_id,
            transaction_type=TransactionType.EXPENSE,
            category=TransactionCategory.LABOR_WAGES,
            amount=amount,
            item_name=item_name,
            cost_class=CostClass.COGS,
            description=description,
            counterparty_name=counterparty_name,
            reference_code=reference_code,
            timestamp=payroll_run.finalized_at,
            recorded_by=actor_id,
            status=TransactionStatus.POSTED.value,
            posted_at=payroll_run.finalized_at,
            posted_by=actor_id,
        ))
