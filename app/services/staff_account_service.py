from __future__ import annotations

from uuid import uuid4

from app import db
from app.models.user import Role, User
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService


class StaffAccountService:
    @staticmethod
    def validate_role(value: str) -> str:
        role = (value or '').strip().upper()
        if role not in Role.assignable_farm_staff_roles():
            allowed = ', '.join(sorted(Role.assignable_farm_staff_roles()))
            raise ValueError(f'role must be one of: {allowed}.')
        return role

    @staticmethod
    def create_linked_account(employee, data: dict, *, role: str, password: str, is_active: bool, requires_password_reset: bool):
        phone_number = AuthService._normalize_phone_number(data.get('phone_number') or employee.phone_number)
        username = (data.get('username') or phone_number).strip()
        email = (data.get('email') or '').strip() or None
        if not phone_number:
            raise ValueError('phone_number is required on the employee or onboarding request.')
        if UserRepository.get_by_username(username) or AuthService._find_user_by_phone(phone_number):
            raise LookupError('An account already uses this username or phone number.')

        account = User(
            tenant_id=employee.tenant_id,
            identifier=f'phone_{phone_number}',
            username=username,
            name=employee.full_name,
            email=email,
            phone_number=phone_number,
            role=role,
            is_active=is_active,
            requires_password_reset=requires_password_reset,
        )
        account.set_password(password or uuid4().hex)
        db.session.add(account)
        db.session.flush()
        employee.user_id = account.id
        return account
