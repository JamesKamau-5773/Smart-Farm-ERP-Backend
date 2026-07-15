"""
Repository layer for AnimalYieldTarget data access.
Follows SRP: handles only persistence logic and queries.
"""

from __future__ import annotations
from typing import Optional
from flask import g, has_app_context
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import db
from app.models.livestock import AnimalYieldTarget, Cow, CowStatus
from app.utils.jwt_payload import parse_public_int_id


def _resolve_tenant_id(tenant_id: int | None = None) -> int | None:
    """Resolve tenant ID from parameter, context, or JWT."""
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


class AnimalYieldTargetRepository:
    """Data access layer for animal yield targets."""

    @staticmethod
    def get_by_id(target_id: int, tenant_id: int | None = None) -> AnimalYieldTarget | None:
        """Get yield target by ID."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(id=target_id)
        if resolved_tenant_id is not None:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.first()

    @staticmethod
    def get_by_cow_id(cow_id: int, tenant_id: int | None = None) -> AnimalYieldTarget | None:
        """Get yield target for a specific cow."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(animal_id=cow_id)
        if resolved_tenant_id is not None:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.first()

    @staticmethod
    def get_active_targets_for_herd(tenant_id: int | None = None) -> list[AnimalYieldTarget]:
        """Get all active yield targets for a tenant, with cow details."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        if resolved_tenant_id is None:
            return []
        
        return (
            AnimalYieldTarget.query
            .filter_by(tenant_id=resolved_tenant_id, status='Active')
            .join(Cow, AnimalYieldTarget.animal_id == Cow.id)
            .filter(Cow.is_active == True, Cow.current_status == CowStatus.LACTATING)
            .all()
        )

    @staticmethod
    def get_all_targets_for_herd(tenant_id: int | None = None) -> list[AnimalYieldTarget]:
        """Get all yield targets (active and inactive) for a tenant."""
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = AnimalYieldTarget.query.filter_by(tenant_id=resolved_tenant_id)
        return query.all()

    @staticmethod
    def create_or_update(
        tenant_id: int,
        cow_id: int,
        target_liters: float,
        times_to_feed_daily: int = 2,
        base_herd_feed_kg: float = 0,
        milking_topup_kg: float = 0,
        status: str = 'Active'
    ) -> AnimalYieldTarget:
        """Create or update yield target for a cow.
        
        Raises:
            ValueError: If cow not found or doesn't belong to tenant
            Exception: If database operation fails
        """
        try:
            # Verify cow exists and belongs to tenant
            cow = Cow.query.filter_by(id=cow_id, tenant_id=tenant_id).first()
            if not cow:
                raise ValueError(f'Cow {cow_id} not found for this tenant.')

            # Get or create target
            target = AnimalYieldTarget.query.filter_by(
                tenant_id=tenant_id,
                animal_id=cow_id
            ).first()

            if target:
                # Update existing
                target.target_liters = target_liters
                target.times_to_feed_daily = times_to_feed_daily
                target.base_herd_feed_kg = base_herd_feed_kg
                target.milking_topup_kg = milking_topup_kg
                target.status = status
            else:
                # Create new
                target = AnimalYieldTarget(
                    tenant_id=tenant_id,
                    animal_id=cow_id,
                    target_liters=target_liters,
                    times_to_feed_daily=times_to_feed_daily,
                    base_herd_feed_kg=base_herd_feed_kg,
                    milking_topup_kg=milking_topup_kg,
                    status=status
                )
                db.session.add(target)

            db.session.commit()
            return target

        except ValueError:
            db.session.rollback()
            raise
        except IntegrityError as e:
            db.session.rollback()
            raise Exception(f'Integrity error creating yield target: {str(e)}')
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f'Database error creating yield target: {str(e)}')

    @staticmethod
    def deactivate(target_id: int, tenant_id: int | None = None) -> bool:
        """Deactivate a yield target."""
        try:
            resolved_tenant_id = _resolve_tenant_id(tenant_id)
            target = AnimalYieldTarget.query.filter_by(id=target_id)
            if resolved_tenant_id is not None:
                target = target.filter_by(tenant_id=resolved_tenant_id)
            
            target = target.first()
            if not target:
                return False

            target.status = 'Inactive'
            db.session.commit()
            return True

        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f'Failed to deactivate yield target: {str(e)}')

    @staticmethod
    def delete(target_id: int, tenant_id: int | None = None) -> bool:
        """Delete a yield target."""
        try:
            resolved_tenant_id = _resolve_tenant_id(tenant_id)
            target = AnimalYieldTarget.query.filter_by(id=target_id)
            if resolved_tenant_id is not None:
                target = target.filter_by(tenant_id=resolved_tenant_id)
            
            target = target.first()
            if not target:
                return False

            db.session.delete(target)
            db.session.commit()
            return True

        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception(f'Failed to delete yield target: {str(e)}')
