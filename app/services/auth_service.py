from __future__ import annotations
from flask import jsonify, current_app
from flask_jwt_extended import create_access_token, decode_token, get_jwt, set_access_cookies, unset_jwt_cookies, verify_jwt_in_request
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import RevokedToken, Role, User
from datetime import datetime, timezone
from app import bcrypt
from app.repositories.user_repo import UserRepository
from app.services.account_state_service import AccountStateService
from app.services.login_identifier_resolver import LoginIdentifierResolver
from app.services.session_service import AuthMethod, SessionService
from app.services.workspace_provisioning_service import WorkspaceProvisioningService, WorkspaceRequest
from app.utils.auth_errors import AuthError
from app.utils.password_policy import PasswordPolicy
from app.utils.phone import InvalidPhoneNumber, phone_identifier, phone_username, to_e164, try_to_e164
from app.utils.jwt_payload import (
    build_auth_payload,
    normalize_tenant_type,
    parse_public_int_id,
)
from app.services.page_access import normalize_page_access

def _error(code, message, status):
    return jsonify({"code": code, "error": message}), status


def _normalize_email(value):
    email = (value or '').strip().lower()
    if not email:
        return None
    local, _, domain = email.partition('@')
    if not local or '.' not in domain or len(email) > 120:
        raise AuthError('VALIDATION_ERROR', 'email must be a valid email address.', fields={'email': 'invalid'})
    return email


class AuthService:
    _dummy_password_hash = None

    @staticmethod
    def _equalize_failed_login_timing(password):
        # Run one bcrypt comparison for unknown identifiers so response time does
        # not reveal whether an account exists.
        if AuthService._dummy_password_hash is None:
            AuthService._dummy_password_hash = bcrypt.generate_password_hash('timing-equalizer').decode('utf-8')
        bcrypt.check_password_hash(AuthService._dummy_password_hash, password or '')

    @staticmethod
    def bootstrap_available():
        """Return whether the initial super-admin bootstrap can be attempted."""
        if not (current_app.config.get('BOOTSTRAP_SUPER_ADMIN_KEY') or '').strip():
            return False
        return User.query.filter_by(role=Role.SUPER_ADMIN).first() is None

    @staticmethod
    def _normalize_phone_number(value):
        """E.164 for a valid number, '' otherwise."""
        return try_to_e164(value) or ''

    @staticmethod
    def _resolve_phone_number(user):
        if getattr(user, 'phone_number', None):
            return user.phone_number
        # Rows created before phone_number was populated.
        identifier = (getattr(user, 'identifier', None) or '').strip()
        if identifier.startswith('phone_'):
            return try_to_e164(identifier[len('phone_'):])
        return None

    @staticmethod
    def _find_user_by_phone(phone_number: str):
        return LoginIdentifierResolver.resolve_phone(phone_number or '')

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
    def _issue_token_and_payload(*, user, tenant, farms, active_farm, auth_method=AuthMethod.PASSWORD, expires_delta=None):
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))
        available_farms = [(f.id, f.name) for f in farms]
        phone_number = AuthService._resolve_phone_number(user)

        payload = build_auth_payload(
            user_id=user.id,
            name=(user.name or user.username),
            username=user.username,
            phone_number=phone_number,
            role=user.role,
            requires_password_reset=bool(user.requires_password_reset),
            farm_location=getattr(user, 'farm_location', None),
            tenant_pk=tenant.id,
            tenant_name=tenant.name,
            tenant_type=tenant_type,
            active_farm_pk=active_farm.id,
            active_farm_name=active_farm.name,
            available_farms=available_farms,
            page_access=normalize_page_access(getattr(user, 'page_access', None), user.role),
        )

        additional_claims = dict(payload)
        additional_claims.pop("sub", None)
        additional_claims.update(SessionService.session_claims(user, auth_method))

        # expires_delta=None means the configured JWT_ACCESS_TOKEN_EXPIRES.
        access_token = create_access_token(
            identity=str(user.id),
            additional_claims=additional_claims,
            expires_delta=expires_delta,
        )

        # Response-only (not in the token): read live from the database.
        payload.update(AccountStateService.describe(user, auth_method))
        return access_token, payload

    @staticmethod
    def start_session(user, *, farm_id=None, auth_method=AuthMethod.PASSWORD, expires_delta=None):
        """Issue a session for an already-authenticated user: the access token in
        the JSON body and in the httpOnly cookie. Every sign-in route ends here."""
        if not user.is_active:
            return _error("ACCOUNT_DISABLED", "Account is disabled. Contact Farm Administrator.", 403)

        tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
        try:
            active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=farm_id)
        except ValueError as e:
            return _error("INVALID_FARM", str(e), 400)

        try:
            access_token, payload = AuthService._issue_token_and_payload(
                user=user,
                tenant=tenant,
                farms=farms,
                active_farm=active_farm,
                auth_method=auth_method,
                expires_delta=expires_delta,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 500

        expires_at = datetime.fromtimestamp(decode_token(access_token)['exp'], tz=timezone.utc)
        response = jsonify({
            "access_token": access_token,
            "session_expires_at": expires_at.isoformat().replace('+00:00', 'Z'),
            **payload,
        })

        # A shortened session also gets a cookie that expires with it.
        set_access_cookies(response, access_token, max_age=int(expires_delta.total_seconds()) if expires_delta else None)
        return response, 200

    @staticmethod
    def authenticate_user(identifier, password, farm_id=None):
        candidates = LoginIdentifierResolver.candidates(identifier)
        if not candidates:
            AuthService._equalize_failed_login_timing(password)
        user = next((candidate for candidate in candidates if candidate.check_password(password)), None)

        if user:
            return AuthService.start_session(user, farm_id=farm_id)

        return _error("INVALID_CREDENTIALS", "Invalid username or password", 401)

    @staticmethod
    def update_profile(user, data, *, ip_address=None):
        """Apply profile edits to a user. Phone and email changes are normalised,
        checked for uniqueness and reset the matching verified flag.
        """
        from app.services.email_verification_service import EmailVerificationService

        data = data or {}
        email_changed = False
        try:
            if 'name' in data:
                user.name = (data.get('name') or '').strip() or user.name
            if 'farm_location' in data:
                user.farm_location = (data.get('farm_location') or '').strip() or None

            if 'phone_number' in data:
                raw = (data.get('phone_number') or '').strip()
                normalized = to_e164(raw) if raw else None
                if normalized != user.phone_number:
                    if normalized and UserRepository.get_by_phone(normalized):
                        return _error("PHONE_IN_USE", "phone_number is already in use by another account", 409)
                    # Empty/null clears the number (disconnects the WhatsApp bot).
                    user.phone_number = normalized
                    user.phone_verified = False

            if 'email' in data:
                normalized_email = _normalize_email(data.get('email'))
                if normalized_email != user.email:
                    conflict = UserRepository.get_by_email_ci(normalized_email) if normalized_email else None
                    if conflict and conflict.id != user.id:
                        return _error("EMAIL_IN_USE", "email is already in use by another account", 409)
                    user.email = normalized_email
                    user.email_verified = False
                    email_changed = bool(normalized_email)

            db.session.commit()
        except InvalidPhoneNumber:
            db.session.rollback()
            return _error("INVALID_PHONE", "phone_number must be a valid phone number.", 400)
        except AuthError as error:
            db.session.rollback()
            return error.to_response()
        except IntegrityError:
            db.session.rollback()
            return _error("DUPLICATE_FIELD", "phone_number or email is already in use by another account", 409)
        except Exception:
            db.session.rollback()
            return jsonify({"error": "Failed to update profile"}), 500

        if email_changed:
            EmailVerificationService.send_if_possible(user, ip_address=ip_address)

        return jsonify({
            "message": "Profile updated",
            "id": user.id,
            "name": user.name,
            "farm_location": getattr(user, 'farm_location', None),
            "phone_number": user.phone_number,
            "email": user.email,
            "account_flags": AccountStateService.account_flags(user),
        }), 200

    @staticmethod
    def register_workspace(data, *, ip_address=None):
        from app.services.email_verification_service import EmailVerificationService

        data = data or {}
        farm_name = (data.get('farm_name') or '').strip()
        raw_phone = (data.get('phone_number') or '').strip()
        password = data.get('password') or ''
        requested_role = (data.get('role') or '').strip().upper()
        bootstrap_key = (data.get('bootstrap_key') or data.get('bootstrapKey') or '').strip()

        if not farm_name:
            return _error("VALIDATION_ERROR", "farm_name is required", 400)
        if not raw_phone:
            return _error("VALIDATION_ERROR", "phone_number is required", 400)
        try:
            phone_number = to_e164(raw_phone)
        except InvalidPhoneNumber:
            return _error("INVALID_PHONE", "phone_number must be a valid phone number.", 400)
        try:
            email = _normalize_email(data.get('email'))
        except AuthError as error:
            return error.to_response()
        username = (data.get('username') or '').strip() or phone_username(phone_number)

        if requested_role == 'SUPER_ADMIN':
            expected_bootstrap_key = (current_app.config.get('BOOTSTRAP_SUPER_ADMIN_KEY') or '').strip()
            if not AuthService.bootstrap_available():
                return _error("BOOTSTRAP_UNAVAILABLE", "SUPER_ADMIN bootstrap is unavailable.", 403)
            if not bootstrap_key or bootstrap_key != expected_bootstrap_key:
                return _error("INVALID_BOOTSTRAP_KEY", "Invalid bootstrap key for SUPER_ADMIN registration.", 403)
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
            return _error("PHONE_IN_USE", "phone_number is already in use", 409)

        if email and UserRepository.get_by_email_ci(email):
            return _error("EMAIL_IN_USE", "email is already in use", 409)
        try:
            PasswordPolicy.enforce(password, personal_values=[username, phone_number, (email or '').split('@')[0]])
        except AuthError as error:
            return error.to_response()

        tenant_name = (data.get('tenant_name') or '').strip() or f"{farm_name} Tenant"
        display_name = (data.get('name') or data.get('full_name') or '').strip() or username
        # A platform super-admin is housed in a standard tenant; never accept a
        # client-selected tenant type for the bootstrap account.
        tenant_type_raw = 'single' if role == 'SUPER_ADMIN' else data.get('tenant_type')

        try:
            tenant_type = normalize_tenant_type(tenant_type_raw)
        except ValueError as e:
            return _error("VALIDATION_ERROR", str(e), 400)

        try:
            user, tenant, farm = WorkspaceProvisioningService.create(WorkspaceRequest(
                farm_name=farm_name,
                tenant_name=tenant_name,
                tenant_type=tenant_type,
                role=role,
                display_name=display_name,
                username=username,
                identifier=data.get('identifier') or phone_identifier(phone_number),
                phone_number=phone_number,
                email=email,
                password=password,
            ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _error("DUPLICATE_ACCOUNT", "Could not complete registration due to duplicate fields", 409)
        except Exception:
            db.session.rollback()
            return jsonify({"error": "Registration failed"}), 500

        if email:
            EmailVerificationService.send_if_possible(user, ip_address=ip_address)

        access_token, payload = AuthService._issue_token_and_payload(
            user=user,
            tenant=tenant,
            farms=[farm],
            active_farm=farm,
        )

        response = jsonify({
            "message": "Workspace registered successfully",
            "access_token": access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 201

    @staticmethod
    def switch_farm(user_id: str, farm_id: str, auth_method: str = AuthMethod.PASSWORD):
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
            auth_method=auth_method,
        )

        response = jsonify({
            "access_token": access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 200

    @staticmethod
    def logout_user():
        verify_jwt_in_request(optional=True)
        claims = get_jwt() or {}
        token_id = claims.get('jti')
        expires_at = claims.get('exp')
        if token_id and expires_at:
            existing = RevokedToken.query.filter_by(jti=token_id).first()
            if not existing:
                db.session.add(RevokedToken(
                    jti=token_id,
                    expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
                ))
                db.session.commit()
        response = jsonify({"message": "Successfully logged out."})
        unset_jwt_cookies(response)
        return response, 200
