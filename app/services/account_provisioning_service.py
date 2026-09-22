from __future__ import annotations

from flask import jsonify
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.hr import EmployeeOnboardingStatus
from app.repositories.hr_repo import EmployeeRepository
from app.services.audit_service import record_audit
from app.services.staff_account_service import StaffAccountService


class AccountProvisioningService:
    @staticmethod
    def provision_employee(tenant_id: int, employee_id: int, data: dict, *, actor_id: int, ip_address=None):
        employee = EmployeeRepository.get_by_id_for_tenant(employee_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404

        password = data.get('password') or ''
        if len(password) < 8:
            return jsonify({'error': 'password must be at least 8 characters.'}), 400
        try:
            role = StaffAccountService.validate_role(data.get('role'))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

        if employee.user and employee.user.is_active:
            return jsonify({'error': 'Employee already has an active linked account.'}), 409

        try:
            account = employee.user
            if account:
                account.role = role
                account.set_password(password)
                account.is_active = True
                account.requires_password_reset = True
            else:
                account = StaffAccountService.create_linked_account(
                    employee,
                    data,
                    role=role,
                    password=password,
                    is_active=True,
                    requires_password_reset=True,
                )

            employee.onboarding_status = EmployeeOnboardingStatus.PASSWORD_RESET_REQUIRED
            employee.onboarding_invite_nonce = None
            employee.onboarding_invite_expires_at = None
            record_audit(
                user_id=actor_id,
                action='PROVISION_STAFF_ACCOUNT',
                entity_type='Employee',
                entity_id=employee.id,
                old_value=None,
                new_value={'role': role, 'status': EmployeeOnboardingStatus.PASSWORD_RESET_REQUIRED},
                ip_address=ip_address,
            )
            db.session.commit()
        except LookupError as error:
            db.session.rollback()
            return jsonify({'error': str(error)}), 409
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Could not provision account due to duplicate account details.'}), 409
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'Could not provision employee account.'}), 500

        return jsonify({
            'message': 'Employee account provisioned successfully.',
            'employee_id': employee.id,
            'onboarding_status': employee.onboarding_status,
            'account': {
                'id': account.id,
                'username': account.username,
                'role': account.role,
                'is_active': account.is_active,
                'requires_password_reset': account.requires_password_reset,
            },
        }), 201
