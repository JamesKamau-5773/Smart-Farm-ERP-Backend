"""Account resolution for social sign-in (Google).

Linking rules:
* An existing SocialAccount signs that user in.
* Otherwise a local account is auto-linked only when both Google and the local
  account have verified the same email address.
* A matching but unverified local email is never linked automatically.
* No match means a new workspace sign-up, carried by a short-lived signed ticket.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.auth import SocialAccount
from app.models.user import Role, User
from app.repositories.social_account_repo import SocialAccountRepository
from app.repositories.user_repo import UserRepository
from app.services.account_state_service import AccountStateService
from app.services.google_identity_provider import GoogleIdentity
from app.services.phone_verification_service import PhoneVerificationService
from app.services.session_service import AuthMethod
from app.services.workspace_provisioning_service import WorkspaceProvisioningService, WorkspaceRequest
from app.utils.auth_errors import AuthError, invalid_phone_error
from app.utils.jwt_payload import normalize_tenant_type
from app.utils.phone import InvalidPhoneNumber, phone_username, to_e164

GOOGLE = 'google'
SIGNUP_TICKET_TTL_SECONDS = 600


class SocialLoginResult:
    SIGNED_IN = 'signed_in'
    PHONE_VERIFICATION_REQUIRED = 'phone_verification_required'
    SIGNUP_REQUIRED = 'signup_required'
    LINK_REQUIRED = 'link_required'
    LINKED = 'linked'
    ERROR = 'error'


@dataclass(frozen=True)
class SocialLoginOutcome:
    result: str
    user: Optional[User] = None
    error_code: Optional[str] = None
    signup_ticket: Optional[str] = None


def _error(code: str) -> SocialLoginOutcome:
    return SocialLoginOutcome(SocialLoginResult.ERROR, error_code=code)


class SignupTicketCodec:
    SALT = 'google-signup-ticket'

    @staticmethod
    def _serializer() -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=SignupTicketCodec.SALT)

    @staticmethod
    def encode(identity: GoogleIdentity) -> str:
        return SignupTicketCodec._serializer().dumps({
            'sub': identity.subject, 'email': identity.email, 'name': identity.name,
        })

    @staticmethod
    def decode(ticket: Optional[str]) -> GoogleIdentity:
        try:
            data = SignupTicketCodec._serializer().loads(ticket or '', max_age=SIGNUP_TICKET_TTL_SECONDS)
        except (BadSignature, SignatureExpired):
            raise AuthError('SIGNUP_SESSION_EXPIRED', 'Your Google sign-up session has expired. Please start again.', 401)
        return GoogleIdentity(subject=data['sub'], email=data['email'], email_verified=True, name=data.get('name') or '')

    @staticmethod
    def remaining_seconds(ticket: str) -> int:
        _, issued_at = SignupTicketCodec._serializer().loads(
            ticket, max_age=SIGNUP_TICKET_TTL_SECONDS, return_timestamp=True,
        )
        elapsed = (datetime.now(timezone.utc) - issued_at).total_seconds()
        return max(int(SIGNUP_TICKET_TTL_SECONDS - elapsed), 0)


class SocialLoginService:
    @staticmethod
    def sign_in(identity: GoogleIdentity) -> SocialLoginOutcome:
        if not identity.email_verified or not identity.email:
            return _error('GOOGLE_EMAIL_UNVERIFIED')

        social = SocialAccountRepository.get(GOOGLE, identity.subject)
        if social:
            return SocialLoginService._signed_in(social.user, social)

        user = UserRepository.get_by_email_ci(identity.email)
        if user is None:
            return SocialLoginOutcome(SocialLoginResult.SIGNUP_REQUIRED, signup_ticket=SignupTicketCodec.encode(identity))
        if not user.email_verified:
            return SocialLoginOutcome(SocialLoginResult.LINK_REQUIRED)
        if SocialAccountRepository.get_for_user(user.id, GOOGLE):
            # The account is already linked to a different Google identity.
            return _error('GOOGLE_ALREADY_LINKED')

        social = SocialAccountRepository.add(SocialAccount(
            user_id=user.id, provider=GOOGLE, provider_user_id=identity.subject, email=identity.email,
        ))
        return SocialLoginService._signed_in(user, social)

    @staticmethod
    def link(identity: GoogleIdentity, user: User) -> SocialLoginOutcome:
        if not identity.email_verified or not identity.email:
            return _error('GOOGLE_EMAIL_UNVERIFIED')
        existing = SocialAccountRepository.get(GOOGLE, identity.subject)
        if existing and existing.user_id != user.id:
            return _error('GOOGLE_ALREADY_LINKED')
        if not existing:
            if SocialAccountRepository.get_for_user(user.id, GOOGLE):
                return _error('GOOGLE_ALREADY_LINKED')
            SocialAccountRepository.add(SocialAccount(
                user_id=user.id, provider=GOOGLE, provider_user_id=identity.subject, email=identity.email,
            ))
        if user.email and user.email == identity.email:
            user.email_verified = True
        db.session.commit()
        return SocialLoginOutcome(SocialLoginResult.LINKED, user=user)

    @staticmethod
    def unlink(user: User) -> None:
        social = SocialAccountRepository.get_for_user(user.id, GOOGLE)
        if not social:
            raise AuthError('NOT_FOUND', 'No Google account is linked.', 404)
        if not user.has_password:
            raise AuthError('LAST_LOGIN_METHOD', 'Set a password before unlinking Google, or you will be locked out.', 409)
        SocialAccountRepository.delete(social)
        db.session.commit()

    @staticmethod
    def complete_signup(data: dict, *, ip_address=None):
        identity = SignupTicketCodec.decode(data.get('signup_token'))
        farm_name = (data.get('farm_name') or '').strip()
        if not farm_name:
            raise AuthError('VALIDATION_ERROR', 'farm_name is required.', fields={'farm_name': 'required'})
        if not data.get('phone_number'):
            raise AuthError('VALIDATION_ERROR', 'phone_number is required.', fields={'phone_number': 'required'})
        try:
            phone = to_e164(data.get('phone_number'))
        except InvalidPhoneNumber:
            raise invalid_phone_error()
        try:
            tenant_type = normalize_tenant_type(data.get('tenant_type'))
        except ValueError as error:
            raise AuthError('VALIDATION_ERROR', str(error), fields={'tenant_type': 'invalid'})

        if SocialAccountRepository.get(GOOGLE, identity.subject) or UserRepository.get_by_email_ci(identity.email):
            raise AuthError('EMAIL_IN_USE', 'An account with this email already exists. Log in instead.', 409)

        holder = UserRepository.get_by_phone(phone)
        if holder and holder.phone_verified:
            raise AuthError('PHONE_IN_USE', 'phone_number is already in use by another account.', 409)
        username = phone_username(phone)
        if UserRepository.get_by_username(username):
            username = f'{username}_{identity.subject[-6:]}'

        display_name = (data.get('name') or identity.name or '').strip() or username
        try:
            user, tenant, farm = WorkspaceProvisioningService.create(WorkspaceRequest(
                farm_name=farm_name,
                tenant_name=(data.get('tenant_name') or '').strip() or f'{farm_name} Tenant',
                tenant_type=tenant_type,
                role=Role.FARMER,
                display_name=display_name,
                username=username,
                identifier=f'google_{identity.subject}',
                # An unverified claim elsewhere is resolved when this user verifies.
                phone_number=None if holder else phone,
                email=identity.email,
                email_verified=True,
            ))
            SocialAccountRepository.add(SocialAccount(
                user_id=user.id, provider=GOOGLE, provider_user_id=identity.subject,
                email=identity.email, last_login_at=datetime.now(timezone.utc),
            ))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise AuthError('DUPLICATE_ACCOUNT', 'Could not complete registration due to duplicate fields.', 409)

        verification = PhoneVerificationService.start(user, phone, ip_address=ip_address)
        return user, tenant, farm, verification

    @staticmethod
    def _signed_in(user: User, social: SocialAccount) -> SocialLoginOutcome:
        if not user.is_active:
            return _error('ACCOUNT_DISABLED')
        social.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        if AccountStateService.requires_phone_verification(user, AuthMethod.GOOGLE):
            return SocialLoginOutcome(SocialLoginResult.PHONE_VERIFICATION_REQUIRED, user=user)
        return SocialLoginOutcome(SocialLoginResult.SIGNED_IN, user=user)
