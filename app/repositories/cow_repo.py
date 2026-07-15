from __future__ import annotations

from flask import g, has_app_context

from app.models.livestock import Cow
from app import db
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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

class CowRepository:
    @staticmethod
    def get_by_livestock_id(livestock_id: int, tenant_id: int | None = None) -> Cow:
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        if resolved_tenant_id is None:
            return db.session.get(Cow, livestock_id)
        return Cow.query.filter_by(id=livestock_id, tenant_id=resolved_tenant_id).first()

    @staticmethod
    def get_by_id(cow_id: int, tenant_id: int | None = None) -> Cow:
        return CowRepository.get_by_livestock_id(cow_id, tenant_id=tenant_id)

    @staticmethod
    def get_by_tag(tag_number: str, tenant_id: int | None = None) -> Cow:
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = Cow.query.filter_by(tag_number=tag_number)
        if resolved_tenant_id is not None:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.first()

    @staticmethod
    def get_by_name(name: str, tenant_id: int | None = None) -> Cow:
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return None

        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = Cow.query.filter(func.lower(Cow.name) == cleaned_name.lower())
        if resolved_tenant_id is not None:
            query = query.filter(Cow.tenant_id == resolved_tenant_id)
        return query.first()

    @staticmethod
    def get_all_active_livestock(tenant_id: int | None = None) -> list:
        resolved_tenant_id = _resolve_tenant_id(tenant_id)
        query = Cow.query.filter_by(is_active=True)
        if resolved_tenant_id is not None:
            query = query.filter_by(tenant_id=resolved_tenant_id)
        return query.all()

    @staticmethod
    def get_all_active() -> list:
        return CowRepository.get_all_active_livestock()

    @staticmethod
    def create_livestock(tag_number: str, date_of_birth, name: str = None, breed_status: str = "Foundation", tenant_id: int | None = None) -> Cow:
        try:
            resolved_tenant_id = _resolve_tenant_id(tenant_id)
            if resolved_tenant_id is None:
                raise ValueError("Missing tenant context.")

            new_livestock = Cow(
                tenant_id=resolved_tenant_id,
                tag_number=tag_number,
                name=name,
                breed_status=breed_status,
                date_of_birth=date_of_birth
            )
            db.session.add(new_livestock)
            db.session.commit()
            return new_livestock
        except IntegrityError:
            db.session.rollback()
            raise ValueError("Cow tag_number already exists for this tenant.")
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while registering cow.")

    @staticmethod
    def create_cow(tag_number: str, date_of_birth, name: str = None, breed_status: str = "Foundation", tenant_id: int | None = None) -> Cow:
        return CowRepository.create_livestock(tag_number, date_of_birth, name=name, breed_status=breed_status, tenant_id=tenant_id)