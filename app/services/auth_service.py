from flask import jsonify, current_app
from flask_jwt_extended import create_access_token, set_access_cookies, unset_jwt_cookies
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
from sqlalchemy import or_

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.utils.jwt_payload import (
    build_auth_payload,
    normalize_tenant_type,
    parse_public_int_id,
)

class AuthService:
    @staticmethod
    def _normalize_phone_number(value):
        raw = (value or '').strip()
        if not raw:
            return ''
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if raw.startswith('+') and digits:
            return digits
        if digits.startswith('0') and len(digits) >= 10:
            return f'254{digits[1:]}'
        return digits or raw

    @staticmethod
    def _resolve_phone_number(user):
        identifier = (getattr(user, 'identifier', None) or '').strip()
        if identifier.startswith('phone_'):
            return identifier[len('phone_'):]
        return (getattr(user, 'username', None) or '').strip()

    @staticmethod
    def _find_user_by_phone(phone_number: str):
        normalized = AuthService._normalize_phone_number(phone_number)
        candidates = {phone_number.strip(), normalized}
        candidates = {candidate for candidate in candidates if candidate}
        if not candidates:
            return None

        identifier_candidates = {f'phone_{candidate}' for candidate in candidates}
        return User.query.filter(
            or_(
                User.username.in_(candidates),
                User.identifier.in_(identifier_candidates),
            )
        ).first()

    @staticmethod
    def _ensure_default_tenant_and_farm(user):
        """Best-effort safety net for older DBs / seedless dev envs."""
        tenant = getattr(user, "tenant", None)
        if tenant is None and getattr(user, "tenant_id", None) is not None:
            tenant = db.session.get(Tenant, user.tenant_id)

        if tenant is None:
            tenant = Tenant(name="Default Tenant", tenant_type="single")
            db.session.add(tenant)
            db.session.flush()
            user.tenant_id = tenant.id
            user.tenant = tenant

        farms = list(getattr(tenant, "farms", []) or [])
        if not farms:
            farm = Farm(tenant_id=tenant.id, name="Default Farm")
            db.session.add(farm)
            db.session.flush()
            farms = [farm]

        db.session.commit()
        return tenant, farms

    @staticmethod
    def _pick_active_farm(*, tenant, farms, requested_farm_id: str | None):
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))

        if tenant_type == "single":
            return farms[0]

        # cooperative
        if requested_farm_id:
            requested_pk = parse_public_int_id(requested_farm_id, "farm_")
            for farm in farms:
                if farm.id == requested_pk:
                    return farm
            raise ValueError("Invalid farm_id for this tenant")

        return farms[0]

    @staticmethod
    def _issue_token_and_payload(*, user, tenant, farms, active_farm):
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))
        available_farms = [(f.id, f.name) for f in farms]
        phone_number = AuthService._resolve_phone_number(user)

        payload = build_auth_payload(
            user_id=user.id,
            name=(user.name or user.username),
            phone_number=phone_number,
            role=user.role,
            farm_location=getattr(user, 'farm_location', None),
            tenant_pk=tenant.id,
            tenant_name=tenant.name,
            tenant_type=tenant_type,
            active_farm_pk=active_farm.id,
            active_farm_name=active_farm.name,
            available_farms=available_farms,
        )

        additional_claims = dict(payload)
        additional_claims.pop("sub", None)

        access_token = create_access_token(
            identity=str(user.id),
            additional_claims=additional_claims,
        )

        return access_token, payload

    @staticmethod
    def authenticate_user(username, password, farm_id=None):
        lookup_value = AuthService._normalize_phone_number(username) or username
        user = UserRepository.get_by_username(lookup_value) or UserRepository.get_by_username(username)
        
        # 1. Verify User Exists and Password Matches
        if user and user.check_password(password):
            
            # 2. Check if account is locked/inactive
            if not user.is_active:
                return jsonify({"error": "Account is disabled. Contact Farm Administrator."}), 403
            
            tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
            try:
                active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=farm_id)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

            try:
                access_token, payload = AuthService._issue_token_and_payload(
                    user=user,
                    tenant=tenant,
                    farms=farms,
                    active_farm=active_farm,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 500

            response = jsonify({
                "access_token": access_token,
                **payload,
            })

            set_access_cookies(response, access_token)
            return response, 200
            
        return jsonify({"error": "Invalid username or password"}), 401

    @staticmethod
    def register_workspace(data):
        data = data or {}
        farm_name = (data.get('farm_name') or '').strip()
        phone_number = AuthService._normalize_phone_number(data.get('phone_number'))
        username = (data.get('username') or phone_number).strip()
        password = data.get('password') or ''
        requested_role = (data.get('role') or '').strip().upper()
        bootstrap_key = (data.get('bootstrap_key') or data.get('bootstrapKey') or '').strip()

        if not farm_name:
            return jsonify({"error": "farm_name is required"}), 400
        if not phone_number:
            return jsonify({"error": "phone_number is required"}), 400
        if not username:
            return jsonify({"error": "username or phone_number is required"}), 400
        if len(password) < 8:
            return jsonify({"error": "password must be at least 8 characters"}), 400

        if requested_role == 'SUPER_ADMIN':
            expected_bootstrap_key = (current_app.config.get('BOOTSTRAP_SUPER_ADMIN_KEY') or '').strip()
            if not expected_bootstrap_key:
                return jsonify({"error": "SUPER_ADMIN bootstrap is not enabled."}), 403
            if not bootstrap_key or bootstrap_key != expected_bootstrap_key:
                return jsonify({"error": "Invalid bootstrap key for SUPER_ADMIN registration."}), 403
            role = 'SUPER_ADMIN'
        else:
            role = 'FARMER'

        existing_user = AuthService._find_user_by_phone(phone_number) or UserRepository.get_by_username(username)
        if existing_user:
            if existing_user.check_password(password):
                tenant = getattr(existing_user, 'tenant', None) or db.session.get(Tenant, existing_user.tenant_id)
                if tenant is None:
                    return jsonify({"error": "Registration failed"}), 500
                farms = list(getattr(tenant, 'farms', []) or [])
                if not farms:
                    farm = Farm(tenant_id=tenant.id, name=farm_name)
                    db.session.add(farm)
                    db.session.flush()
                    farms = [farm]
                active_farm = farms[0]
                access_token, payload = AuthService._issue_token_and_payload(
                    user=existing_user,
                    tenant=tenant,
                    farms=farms,
                    active_farm=active_farm,
                )
                response = jsonify({
                    "message": "Workspace already exists",
                    "phone_number": AuthService._resolve_phone_number(existing_user),
                    "access_token": access_token,
                    **payload,
                })
                set_access_cookies(response, access_token)
                return response, 200
            return jsonify({"error": "phone_number is already in use"}), 409

        tenant_name = (data.get('tenant_name') or '').strip() or f"{farm_name} Tenant"
        display_name = (data.get('name') or '').strip() or username
        tenant_type_raw = data.get('tenant_type')

        try:
            tenant_type = normalize_tenant_type(tenant_type_raw)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        try:
            tenant = Tenant(name=tenant_name, tenant_type=tenant_type)
            db.session.add(tenant)
            db.session.flush()

            farm = Farm(tenant_id=tenant.id, name=farm_name)
            db.session.add(farm)
            db.session.flush()

            user = User(
                tenant_id=tenant.id,
                identifier=data.get('identifier') or f"phone_{phone_number}",
                username=username or phone_number,
                name=display_name,
                email=None,
                role=role,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "Could not complete registration due to duplicate fields"}), 409
        except Exception:
            db.session.rollback()
            return jsonify({"error": "Registration failed"}), 500

        access_token, payload = AuthService._issue_token_and_payload(
            user=user,
            tenant=tenant,
            farms=[farm],
            active_farm=farm,
        )

        response = jsonify({
            "message": "Workspace registered successfully",
            "phone_number": phone_number,
            "access_token": access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 201

    @staticmethod
    def switch_farm(user_id: str, farm_id: str):
        user = UserRepository.get_by_id(int(user_id))
        if not user:
            return jsonify({"error": "User not found"}), 404

        tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))
        if tenant_type != "cooperative":
            return jsonify({"error": "Farm switching is only allowed for cooperative tenants"}), 403

        try:
            active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=farm_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        access_token, payload = AuthService._issue_token_and_payload(
            user=user,
            tenant=tenant,
            farms=farms,
            active_farm=active_farm,
        )

        response = jsonify({
            "access_token": access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 200

    @staticmethod
    def logout_user():
        response = jsonify({"message": "Successfully logged out."})
        unset_jwt_cookies(response)
        return response, 200