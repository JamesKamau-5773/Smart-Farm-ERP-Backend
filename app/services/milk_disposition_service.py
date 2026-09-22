from datetime import date
from decimal import Decimal, InvalidOperation

from app import db
from app.models.livestock import CowStatus
from app.models.supply import MilkDispositionType
from app.repositories.cow_repo import CowRepository
from app.repositories.milk_disposition_repo import MilkDispositionRepository


class MilkDispositionValidationError(ValueError):
    pass


class MilkDispositionConflictError(ValueError):
    pass


class MilkDispositionService:
    @staticmethod
    def record_calf_feeding(*, tenant_id, user_id, data):
        disposition_type = data.get('type', data.get('disposition_type', MilkDispositionType.CALF_FEED))
        if disposition_type != MilkDispositionType.CALF_FEED:
            raise MilkDispositionValidationError('type must be CALF_FEED.')
        calf_id = data.get('calf_id', data.get('calfId'))
        liters_raw = data.get('liters', data.get('amount'))
        disposition_date = MilkDispositionService._parse_date(
            data.get('disposition_date', data.get('dispositionDate', data.get('date')))
        )

        try:
            calf_id = int(calf_id)
        except (TypeError, ValueError):
            raise MilkDispositionValidationError('calf_id must be an integer.')

        try:
            liters = Decimal(str(liters_raw)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            raise MilkDispositionValidationError('liters must be a valid number.')
        if liters <= 0:
            raise MilkDispositionValidationError('liters must be greater than zero.')

        calf = CowRepository.get_by_id(calf_id, tenant_id=tenant_id)
        if not calf or not calf.is_active:
            raise MilkDispositionValidationError('Active calf not found for this tenant.')
        if calf.current_status != CowStatus.CALF:
            raise MilkDispositionValidationError('Selected animal must have Calf status.')

        try:
            produced = MilkDispositionRepository.lock_saleable_production(
                tenant_id=tenant_id,
                disposition_date=disposition_date,
            )
            usage = MilkDispositionRepository.inventory_usage(
                tenant_id=tenant_id,
                disposition_date=disposition_date,
            )
            available = produced - sum(usage.values(), Decimal('0'))
            if liters > available:
                raise MilkDispositionConflictError(
                    'Calf feeding exceeds available milk for this date. '
                    f'Available: {max(available, Decimal("0")):.2f} liters.'
                )
            disposition = MilkDispositionRepository.create(
                tenant_id=tenant_id,
                disposition_type=MilkDispositionType.CALF_FEED,
                disposition_date=disposition_date,
                liters=liters,
                calf_id=calf.id,
                notes=(data.get('notes') or '').strip() or None,
                recorded_by=int(user_id),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        return MilkDispositionService.serialize(disposition)

    @staticmethod
    def list_dispositions(*, tenant_id, disposition_date=None, calf_id=None):
        parsed_date = MilkDispositionService._parse_date(disposition_date) if disposition_date else None
        if calf_id is not None:
            try:
                calf_id = int(calf_id)
            except (TypeError, ValueError):
                raise MilkDispositionValidationError('calf_id must be an integer.')
        rows = MilkDispositionRepository.list_for_tenant(
            tenant_id=tenant_id,
            disposition_date=parsed_date,
            calf_id=calf_id,
        )
        return [MilkDispositionService.serialize(row) for row in rows]

    @staticmethod
    def serialize(disposition):
        return {
            'id': disposition.id,
            'type': disposition.disposition_type,
            'disposition_type': disposition.disposition_type,
            'date': disposition.disposition_date.isoformat(),
            'disposition_date': disposition.disposition_date.isoformat(),
            'liters': float(disposition.liters),
            'calf_id': disposition.calf_id,
            'calf': {
                'id': disposition.calf.id,
                'tag_number': disposition.calf.tag_number,
                'name': disposition.calf.name,
            },
            'notes': disposition.notes,
            'recorded_by': disposition.recorded_by,
            'created_at': disposition.created_at.isoformat(),
        }

    @staticmethod
    def _parse_date(raw):
        if raw in (None, ''):
            return date.today()
        try:
            parsed = date.fromisoformat(str(raw))
        except (TypeError, ValueError):
            raise MilkDispositionValidationError('date must be in YYYY-MM-DD format.')
        if parsed > date.today():
            raise MilkDispositionValidationError('date cannot be in the future.')
        return parsed
