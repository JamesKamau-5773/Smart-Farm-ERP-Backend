"""Two-factor authentication for the SUPER_ADMIN: enrolment, verification, recovery codes.

* Enrolment: a TOTP secret (encrypted at rest) and an otpauth:// URI for a QR code.
  Confirming it with a first code returns 10 single-use recovery codes, shown once
  and stored only as keyed hashes.
* Verification: a TOTP code (never the same time step twice) or a recovery code.
* Success issues a new, shorter session and records its token id in mfa_sessions:
  2FA completion lives on the server, not in a client flag. The pre-2FA token is revoked.

Re-enrolment is only possible after ``flask platform reset-2fa`` (server-side).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from app import db
from app.models.mfa import MfaSession, UserMfaCredential, UserMfaRecoveryCode
from app.models.user import RevokedToken, Role, User
from app.services.audit_service import record_audit
from app.services.totp_service import TotpService
from app.utils import secret_cipher
from app.utils.api_errors import ApiError
from app.utils.secret_hashing import hash_secret

RECOVERY_CODE_COUNT = 10
_RECOVERY_PURPOSE = 'mfa-recovery-code'
_RECOVERY_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'  # no 0/o, 1/l/i


class MfaMethod:
    TOTP = 'totp'
    RECOVERY_CODE = 'recovery_code'
    ENROLMENT = 'enrolment'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalize_recovery_code(value: str) -> str:
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())


class MfaService:
    # -- state ------------------------------------------------------------------------------
    @staticmethod
    def applies_to(user: Optional[User]) -> bool:
        """2FA is required for the SUPER_ADMIN role (checked live, wherever the account lives)."""
        return bool(user is not None and user.role == Role.SUPER_ADMIN)

    @staticmethod
    def _credential(user: User) -> Optional[UserMfaCredential]:
        return db.session.get(UserMfaCredential, user.id)

    @staticmethod
    def is_enrolled(user: User) -> bool:
        credential = MfaService._credential(user)
        return bool(credential and credential.confirmed_at)

    @staticmethod
    def session_verified(user: Optional[User], jti: Optional[str], *, now: Optional[datetime] = None) -> bool:
        if user is None or not jti:
            return False
        session = db.session.get(MfaSession, jti)
        return bool(session and session.user_id == user.id and _aware(session.expires_at) > (now or _now()))

    @staticmethod
    def describe(user: User, jti: Optional[str]) -> dict:
        if not MfaService.applies_to(user):
            return {'mfa_enrolled': False, 'mfa_verified': False}
        return {
            'mfa_enrolled': MfaService.is_enrolled(user),
            'mfa_verified': MfaService.session_verified(user, jti),
        }

    # -- enrolment --------------------------------------------------------------------------
    @staticmethod
    def start_enrolment(user: User) -> dict:
        MfaService._require_super_admin(user)
        MfaService._require_cipher()
        credential = MfaService._credential(user)
        if credential and credential.confirmed_at:
            raise ApiError('MFA_ALREADY_ENROLLED', 'Two-factor authentication is already set up.', 409)

        secret = TotpService.new_secret()
        if credential is None:
            credential = UserMfaCredential(user_id=user.id, secret_ciphertext='')
            db.session.add(credential)
        credential.secret_ciphertext = secret_cipher.encrypt(secret)
        credential.last_used_step = None
        db.session.commit()
        return {
            'secret': secret,
            'otpauth_uri': TotpService.provisioning_uri(
                secret,
                account_name=user.username or f'user-{user.id}',
                issuer=current_app.config.get('MFA_ISSUER') or 'Maziwa Smart',
            ),
        }

    @staticmethod
    def confirm_enrolment(user: User, code: str, *, claims: dict, ip_address=None, now=None):
        MfaService._require_super_admin(user)
        MfaService._require_cipher()
        credential = MfaService._credential(user)
        if credential is None:
            raise ApiError('MFA_ENROLLMENT_NOT_STARTED', 'Start two-factor setup first.', 409)
        if credential.confirmed_at:
            raise ApiError('MFA_ALREADY_ENROLLED', 'Two-factor authentication is already set up.', 409)

        step = TotpService.matching_step(MfaService._secret(credential), code, now=now)
        if step is None:
            MfaService._record_failure(user, MfaMethod.ENROLMENT, ip_address)
            raise ApiError('MFA_INVALID_CODE', 'That code is not valid. Check the time on your phone and try again.', 401)

        credential.confirmed_at = now or _now()
        credential.last_used_step = step
        codes = MfaService._replace_recovery_codes(user)
        record_audit(
            user_id=user.id, action='MFA_ENROLLED', entity_type='User', entity_id=user.id,
            old_value=None, new_value={'method': 'totp', 'recovery_codes': RECOVERY_CODE_COUNT},
            ip_address=ip_address,
        )
        response, status = MfaService._issue_verified_session(user, MfaMethod.ENROLMENT, claims)
        if status == 200:
            body = response.get_json()
            body['recovery_codes'] = codes  # Shown once; only hashes are stored.
            response.set_data(current_app.json.dumps(body))
        return response, status

    # -- verification -----------------------------------------------------------------------
    @staticmethod
    def verify(user: User, *, code: Optional[str] = None, recovery_code: Optional[str] = None,
               claims: dict, ip_address=None, now=None):
        MfaService._require_super_admin(user)
        MfaService._require_cipher()
        credential = MfaService._credential(user)
        if not (credential and credential.confirmed_at):
            raise ApiError('MFA_NOT_ENROLLED', 'Set up two-factor authentication first.', 409)

        if code:
            step = TotpService.matching_step(
                MfaService._secret(credential), code, last_used_step=credential.last_used_step, now=now,
            )
            if step is None:
                MfaService._record_failure(user, MfaMethod.TOTP, ip_address)
                raise ApiError('MFA_INVALID_CODE', 'That code is not valid. Check the time on your phone and try again.', 401)
            credential.last_used_step = step
            method = MfaMethod.TOTP
        elif recovery_code:
            if not MfaService._use_recovery_code(user, recovery_code, now=now):
                MfaService._record_failure(user, MfaMethod.RECOVERY_CODE, ip_address)
                raise ApiError('MFA_INVALID_CODE', 'That recovery code is not valid or was already used.', 401)
            remaining = UserMfaRecoveryCode.query.filter_by(user_id=user.id, used_at=None).count()
            record_audit(
                user_id=user.id, action='MFA_RECOVERY_CODE_USED', entity_type='User', entity_id=user.id,
                old_value=None, new_value={'remaining_recovery_codes': remaining}, ip_address=ip_address,
            )
            method = MfaMethod.RECOVERY_CODE
        else:
            raise ApiError('VALIDATION_ERROR', 'Send code or recovery_code.', 400)

        return MfaService._issue_verified_session(user, method, claims)

    # -- reset (server-side only: flask platform reset-2fa) ---------------------------------------
    @staticmethod
    def clear(user: User) -> dict:
        """Removes the secret, recovery codes and verified sessions. Flushes; the caller commits."""
        removed = {
            'credential': UserMfaCredential.query.filter_by(user_id=user.id).delete(),
            'recovery_codes': UserMfaRecoveryCode.query.filter_by(user_id=user.id).delete(),
            'verified_sessions': MfaSession.query.filter_by(user_id=user.id).delete(),
        }
        db.session.flush()
        return removed

    # -- helpers ----------------------------------------------------------------------------
    @staticmethod
    def _require_super_admin(user: User) -> None:
        if not MfaService.applies_to(user):
            raise ApiError('MFA_NOT_AVAILABLE', 'Two-factor authentication is only used by the platform admin.', 403)

    @staticmethod
    def _require_cipher() -> None:
        if not secret_cipher.is_configured():
            raise ApiError('MFA_NOT_CONFIGURED', 'Two-factor authentication is not configured on this server.', 503)

    @staticmethod
    def _secret(credential: UserMfaCredential) -> str:
        try:
            return secret_cipher.decrypt(credential.secret_ciphertext)
        except secret_cipher.SecretCipherError as error:
            raise ApiError(
                'MFA_NOT_CONFIGURED',
                'The two-factor secret cannot be read with the configured keys. Reset 2FA on the server.',
                503,
            ) from error

    @staticmethod
    def _new_recovery_code() -> str:
        raw = ''.join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        return f'{raw[:5]}-{raw[5:]}'

    @staticmethod
    def _replace_recovery_codes(user: User) -> list:
        UserMfaRecoveryCode.query.filter_by(user_id=user.id).delete()
        codes = []
        while len(codes) < RECOVERY_CODE_COUNT:
            code = MfaService._new_recovery_code()
            if code not in codes:
                codes.append(code)
        for code in codes:
            db.session.add(UserMfaRecoveryCode(
                user_id=user.id,
                code_hash=hash_secret(_normalize_recovery_code(code), purpose=_RECOVERY_PURPOSE),
            ))
        return codes

    @staticmethod
    def _use_recovery_code(user: User, supplied: str, *, now=None) -> bool:
        normalized = _normalize_recovery_code(supplied)
        if len(normalized) != 10:
            return False
        digest = hash_secret(normalized, purpose=_RECOVERY_PURPOSE)
        match = (
            UserMfaRecoveryCode.query
            .filter_by(user_id=user.id, code_hash=digest, used_at=None)
            .with_for_update()
            .first()
        )
        if match is None:
            return False
        match.used_at = now or _now()
        return True

    @staticmethod
    def _record_failure(user: User, method: str, ip_address) -> None:
        # The endpoints are rate-limited per user and per IP, which bounds how many of these
        # entries an attacker can create. The submitted code is never stored.
        db.session.rollback()
        record_audit(
            user_id=user.id, action='MFA_FAILED', entity_type='User', entity_id=user.id,
            old_value=None, new_value={'method': method}, ip_address=ip_address,
        )
        db.session.commit()

    @staticmethod
    def _issue_verified_session(user: User, method: str, claims: dict):
        from app.services.auth_service import AuthService
        from app.services.session_service import SessionService

        lifetime = timedelta(minutes=int(current_app.config.get('PLATFORM_ADMIN_SESSION_MINUTES') or 30))

        def record_session(jti: str, expires_at: datetime) -> None:
            db.session.add(MfaSession(jti=jti, user_id=user.id, method=method, expires_at=expires_at))
            db.session.flush()

        response, status = AuthService.start_session(
            user,
            auth_method=SessionService.auth_method_from_claims(claims),
            expires_delta=lifetime,
            on_issued=record_session,
        )
        if status != 200:
            db.session.rollback()
            return response, status

        # The pre-2FA token is done: it cannot be used again.
        old_jti, old_exp = (claims or {}).get('jti'), (claims or {}).get('exp')
        if old_jti and old_exp and not RevokedToken.query.filter_by(jti=old_jti).first():
            db.session.add(RevokedToken(jti=old_jti, expires_at=datetime.fromtimestamp(old_exp, tz=timezone.utc)))
        db.session.commit()
        return response, status
