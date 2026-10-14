from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from app import db
from app.models.finance import (
    CostClass,
    PaymentStatus,
    Transaction,
    TransactionAuditLog,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.models.livestock import BreedingLog
from app.repositories.breeding_repo import BreedingLogRepository, HeatObservationRepository
from app.services.animal_timeline_service import AnimalTimelineService
from app.services.audit_service import record_audit
from app.services.breeding_service import BreedingService
from app.services.reproduction_service import ReproductionService


class BreedingAccountingService:
    """Creates a breeding record and its accounting expense atomically."""

    _AI_SERVICE_COA_CODE = '6105'

    @staticmethod
    def _parse_service_fee(value):
        if value in (None, ''):
            return None
        try:
            fee = Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError('service_fee must be a valid non-negative number.') from exc
        if not fee.is_finite() or fee < 0:
            raise ValueError('service_fee must be a valid non-negative number.')
        return fee

    @staticmethod
    def _resolve_counterparty(provided_by: str):
        if provided_by == 'FARM':
            return 'Farm Inventory'
        return 'Veterinary Service Provider'

    @staticmethod
    def _build_transaction(
        *,
        tenant_id: int,
        farm_id: int | None,
        user_id: int | None,
        breeding_log: BreedingLog,
        amount: Decimal,
        counterparty_name: str,
        ip_address: str | None,
    ) -> Transaction:
        timestamp = datetime.now(timezone.utc)
        transaction = Transaction(
            tenant_id=tenant_id,
            farm_id=farm_id,
            transaction_type=TransactionType.EXPENSE,
            category=TransactionCategory.AI_SERVICE,
            amount=amount,
            item_name='AI service',
            cost_class=CostClass.COGS,
            description='Artificial insemination service fee',
            counterparty_name=counterparty_name[:120],
            source_document_id=breeding_log.id,
            source_document_type='BREEDING_LOG',
            source_cow_id=breeding_log.cow_id,
            source_technician_id=None,
            chart_of_accounts_code=BreedingAccountingService._AI_SERVICE_COA_CODE,
            payment_status=PaymentStatus.PAYABLE.value,
            timestamp=timestamp,
            recorded_by=user_id,
            reference_code=f'BREEDING-FEE-{breeding_log.id}',
            status=TransactionStatus.POSTED.value,
            posted_at=timestamp,
            posted_by=user_id,
        )
        db.session.add(transaction)
        db.session.flush()

        record_audit(
            user_id=user_id,
            action='CREATE_AI_SERVICE_EXPENSE',
            entity_type='Transaction',
            entity_id=transaction.id,
            old_value=None,
            new_value={
                'breeding_log_id': breeding_log.id,
                'amount': str(amount),
                'category': transaction.category.value,
                'source_document_type': transaction.source_document_type,
                'chart_of_accounts_code': transaction.chart_of_accounts_code,
                'payment_status': transaction.payment_status,
            },
            ip_address=ip_address,
        )
        db.session.add(TransactionAuditLog(
            tenant_id=tenant_id,
            transaction_id=transaction.id,
            action='CREATED_FROM_BREEDING_LOG',
            performed_by=user_id,
            ip_address=ip_address,
            details={
                'breeding_log_id': breeding_log.id,
                'cow_id': breeding_log.cow_id,
                'source_document_id': transaction.source_document_id,
                'source_document_type': transaction.source_document_type,
                'chart_of_accounts_code': transaction.chart_of_accounts_code,
            },
        ))
        return transaction

    @staticmethod
    def _create_breeding_log(tenant_id: int, user_id: int | None, data: dict) -> BreedingLog:
        cow_identifier = data.get('cow_id', data.get('cowId'))
        semen_identifier = data.get('semen_id', data.get('semenId'))
        if not semen_identifier:
            semen_identifier = data.get('semen_code', data.get('semenCode'))
        external_sire_code = data.get('external_sire_code', data.get('externalSireCode'))
        if not external_sire_code:
            external_sire_code = data.get('sireCode', data.get('sire_code'))
        provided_by_raw = data.get('provided_by', data.get('providedBy'))
        if not provided_by_raw:
            provided_by_raw = data.get('semen_source', data.get('semenSource', 'FARM'))
        provided_by = BreedingService._normalize_provider(provided_by_raw)
        sire_pta_scores_raw = data.get('sire_pta_scores', data.get('sirePTAScores'))
        insemination_date_raw = data.get('insemination_date', data.get('inseminationDate'))
        if not insemination_date_raw:
            insemination_date_raw = data.get('aiDate', data.get('ai_date'))

        if provided_by not in BreedingService.VALID_SEMEN_PROVIDERS:
            raise ValueError('provided_by must be FARM or VET.')
        if not cow_identifier or not insemination_date_raw:
            raise ValueError('cow_id and insemination_date are required.')
        if provided_by == 'FARM' and not semen_identifier:
            raise ValueError('semen_id is required when provided_by is FARM.')

        try:
            insemination_date = datetime.strptime(str(insemination_date_raw), '%Y-%m-%d').date()
        except ValueError as exc:
            raise ValueError('Invalid insemination_date format (YYYY-MM-DD).') from exc

        cow = BreedingService._resolve_cow(tenant_id, cow_identifier)
        if cow is None:
            raise ValueError('Cow not found.')

        heat_observation = None
        heat_observation_id = data.get('heat_observation_id', data.get('heatObservationId'))
        if heat_observation_id not in (None, ''):
            parsed_observation_id = BreedingService._parse_int(heat_observation_id)
            heat_observation = HeatObservationRepository.get_by_id_for_tenant(parsed_observation_id, tenant_id)
            if heat_observation is None:
                raise ValueError('Heat observation not found for this tenant.')
            if heat_observation.cow_id != cow.id:
                raise ValueError('Heat observation belongs to a different cow.')
            if heat_observation.breeding_log_id is not None:
                raise ValueError('Heat observation is already linked to an insemination.')

        semen = BreedingService._resolve_semen(tenant_id, semen_identifier, provided_by)
        resolved_external_sire_code = None
        stock_level_remaining = None
        if provided_by == 'FARM':
            if semen is None:
                raise ValueError('Semen inventory item not found for this tenant.')
            if semen.stock_level > 0:
                semen.stock_level -= 1
            stock_level_remaining = semen.stock_level
            if sire_pta_scores_raw in (None, '') and isinstance(semen.traits_to_improve, dict):
                sire_pta_scores_raw = semen.traits_to_improve
        else:
            resolved_external_sire_code = str(external_sire_code or semen_identifier or '').strip()
            if not resolved_external_sire_code:
                raise ValueError('external_sire_code is required when provided_by is VET.')

        try:
            sire_pta_scores = BreedingService._parse_sire_pta_scores(sire_pta_scores_raw)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        try:
            service_fee = BreedingService._parse_service_fee(data.get('service_fee', data.get('serviceFee')))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        milestones = ReproductionService.calculate_milestones(insemination_date)
        log = BreedingLogRepository.create(
            tenant_id=tenant_id,
            cow_id=cow.id,
            inventory_semen_id=semen.id if semen else None,
            external_sire_code=resolved_external_sire_code,
            provided_by=provided_by,
            sire_pta_scores=sire_pta_scores,
            insemination_date=insemination_date,
            expected_calving_date=milestones['expected_calving_date'],
            status='Pending',
        )
        log.insemination_time = BreedingService._extract_insemination_time(data)
        log.certificate_number = (data.get('certificate_number') or data.get('certificateNo') or '').strip() or None
        log.technician_name = (data.get('technician_name') or data.get('technicianName') or '').strip() or None
        log.owner_name = (data.get('owner_name') or data.get('ownerName') or '').strip() or None
        log.farm_location = (data.get('farm_location') or data.get('farmLocation') or '').strip() or None
        log.service_fee = service_fee
        log.is_repeat_service = bool(data.get('is_repeat_service', data.get('isRepeatService', False)))
        log.certificate_image_url = (data.get('certificate_image_url') or data.get('certificateImageUrl') or '').strip() or None
        if heat_observation is not None:
            heat_observation.breeding_log_id = log.id

        cow_logs = BreedingLogRepository.list_by_cow(cow.id, tenant_id)
        latest_log_id = cow_logs[0].id
        superseded_logs = []
        for previous_log in cow_logs[1:]:
            if previous_log.status == 'Pending':
                previous_log.status = 'Failed'
                superseded_logs.append(previous_log)
        if log.id != latest_log_id:
            log.status = 'Failed'

        AnimalTimelineService.record_event(
            tenant_id=tenant_id,
            cow_id=cow.id,
            event_type='breeding',
            title=f"Inseminated with {semen.bull_name if semen else log.external_sire_code or 'Unknown sire'}",
            description=f"Status: {log.status} | Expected calving: {milestones['expected_calving_date'].isoformat()}",
            event_date=insemination_date,
            event_data={
                'breeding_log_id': log.id,
                'provided_by': log.provided_by,
                'expected_calving_date': milestones['expected_calving_date'].isoformat(),
                'pregnancy_check_date': milestones['pregnancy_check_date'].isoformat(),
                'status': log.status,
            },
        )
        return log, stock_level_remaining, superseded_logs

    @classmethod
    def create_with_expense(
        cls,
        *,
        tenant_id: int,
        user_id: int | None,
        data: dict,
        ip_address: str | None = None,
        farm_id: int | None = None,
    ):
        fee = cls._parse_service_fee(data.get('service_fee', data.get('serviceFee')))
        provider = str(data.get('provided_by', data.get('providedBy', 'FARM'))).strip().upper()
        if provider not in BreedingService.VALID_SEMEN_PROVIDERS:
            raise ValueError('provided_by must be FARM or VET.')

        log, stock_level_remaining, superseded_logs = cls._create_breeding_log(tenant_id, user_id, data)
        transaction = None
        if fee is not None and fee > 0:
            transaction = cls._build_transaction(
                tenant_id=tenant_id,
                farm_id=farm_id,
                user_id=user_id,
                breeding_log=log,
                amount=fee,
                counterparty_name=cls._resolve_counterparty(provider),
                ip_address=ip_address,
            )
        db.session.commit()
        for superseded_log in superseded_logs:
            AnimalTimelineService.record_event(
                tenant_id=tenant_id,
                cow_id=log.cow_id,
                event_type='breeding_status_update',
                title='Insemination unsuccessful',
                description='Superseded by a later insemination.',
                event_date=datetime.combine(superseded_log.insemination_date, datetime.min.time(), tzinfo=timezone.utc),
                event_data={
                    'breeding_log_id': superseded_log.id,
                    'status': 'Failed',
                    'reason': 'Superseded by a later insemination',
                },
            )
        response = BreedingService._build_insemination_payload(
            log,
            ReproductionService.calculate_milestones(log.insemination_date),
        )
        response['stock_level_remaining'] = stock_level_remaining
        if transaction is not None:
            response['expense'] = {
                'id': transaction.id,
                'amount': float(transaction.amount),
                'category': transaction.category.value,
                'reference_code': transaction.reference_code,
                'source_document_id': transaction.source_document_id,
                'source_document_type': transaction.source_document_type,
                'chart_of_accounts_code': transaction.chart_of_accounts_code,
                'payment_status': transaction.payment_status,
            }
        return jsonify(response), 201
