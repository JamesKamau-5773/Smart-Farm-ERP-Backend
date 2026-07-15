from __future__ import annotations
"""
Repository for AnimalYieldTarget model operations.
Single Responsibility: Database access and persistence for yield targets.
"""
from app.models.livestock import AnimalYieldTarget, Cow, CowStatus
from app import db
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask import has_app_context, g
from app.utils.jwt_payload import parse_public_int_id


def _resolve_tenant_id(tenant_id: int | None = None) -> int | None:
    if tenant_id is not None:
        return tenant_id
    if has_app_context():
        tenant_public_id = getattr(g, 'tenant_id', None)
        if tenant_public_id:
            try:
                return parse_public_int_id(tenant_public_id, 'tenant_')
            except (TypeError, ValueError):
                return None
    return None


class YieldTargetRepository:
    """Data access layer for AnimalYieldTarget records."""

    @staticmethod
    def get_by_id(target_id: int, tenant_id: int | None = None) -> AnimalYieldTarget | None:
        """Fetch a single yield target by ID."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(id=target_id)
        if resolved_tenant_id:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.first()

    @staticmethod
    def get_by_animal_id(animal_id: int, tenant_id: int | None = None) -> AnimalYieldTarget | None:
        """Fetch yield target for a specific cow."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(animal_id=animal_id)
        if resolved_tenant_id:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.first()

    @staticmethod
    def get_all_active(tenant_id: int | None = None) -> list[AnimalYieldTarget]:
        """Fetch all active yield targets for tenant, joined with cow data."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(status='Active')
        if resolved_tenant_id:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.all()

    @staticmethod
    def get_all_for_lactating_cows(tenant_id: int | None = None) -> list[AnimalYieldTarget]:
        """Fetch yield targets only for cows currently in LACTATING status."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = db.session.query(AnimalYieldTarget).join(
            Cow, AnimalYieldTarget.animal_id == Cow.id
        ).filter(
            AnimalYieldTarget.status == 'Active',
            Cow.current_status == CowStatus.LACTATING,
            Cow.is_active == True
        )
        if resolved_tenant_id:
            query = query.filter(AnimalYieldTarget.tenant_id == resolved_tenant_id)
        return query.all()

    @staticmethod
    def create(
        tenant_id: int,
        animal_id: int,
        target_liters: float,
        base_herd_feed_kg: float = 0.0,
        times_to_feed_daily: int = 2,
    ) -> AnimalYieldTarget:
        """Create a new yield target. Raises ValueError on constraint violation."""
        try:
            # Check if cow exists and belongs to tenant
            cow = Cow.query.filter_by(id=animal_id, tenant_id=tenant_id).first()
            if not cow:
                raise ValueError(f"Cow {animal_id} not found for this tenant.")

            target = AnimalYieldTarget(
                tenant_id=tenant_id,
                animal_id=animal_id,
                target_liters=target_liters,
                base_herd_feed_kg=base_herd_feed_kg,
                times_to_feed_daily=times_to_feed_daily,
                status='Active',
            )
            db.session.add(target)
            db.session.commit()
            return target
        except IntegrityError as e:
            db.session.rollback()
            if 'animal_id' in str(e):
                raise ValueError(f"Yield target already exists for cow {animal_id}.")
            raise ValueError("Failed to create yield target due to constraint violation.")
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error while creating yield target: {str(e)}")

    @staticmethod
    def update(
        target_id: int,
        tenant_id: int | None = None,
        **updates
    ) -> AnimalYieldTarget:
        """Update yield target. Supports: target_liters, times_to_feed_daily, status."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(id=target_id)
        if resolved_tenant_id:
            query = query.filter_by(tenant_id=resolved_tenant_id)

        target = query.first()
        if not target:
            raise ValueError(f"Yield target {target_id} not found.")

        try:
            allowed_fields = {'target_liters', 'times_to_feed_daily', 'status', 'base_herd_feed_kg'}
            for key, value in updates.items():
                if key in allowed_fields and value is not None:
                    setattr(target, key, value)

            db.session.commit()
            return target
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error while updating yield target: {str(e)}")

    @staticmethod
    def deactivate(target_id: int, tenant_id: int | None = None) -> AnimalYieldTarget:
        """Deactivate a yield target (mark as inactive)."""
        return YieldTargetRepository.update(target_id, tenant_id=tenant_id, status='Inactive')

    @staticmethod
    def delete(target_id: int, tenant_id: int | None = None) -> bool:
        """Delete a yield target."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(id=target_id)
        if resolved_tenant_id:
            query = query.filter_by(tenant_id=resolved_tenant_id)

        target = query.first()
        if not target:
            return False

        try:
            db.session.delete(target)
            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f"Database error while deleting yield target: {str(e)}")
