"""Password resets issued by a farm owner or administrator for their own users."""
from __future__ import annotations

from app import db
from app.models.user import Role, User
from app.repositories.user_repo import UserRepository
from app.services.audit_service import record_audit
from app.services.password_reset_link_service import PasswordResetLinkService
from app.services.session_service import SessionService
from app.services.verification_challenge_service import VerificationChallengeService
from app.utils.auth_errors import AuthError
from app.utils.jwt_payload import normalize_tenant_type

# Higher rank may reset strictly lower rank within the same tenant.
_ROLE_RANK = {
    Role.SUPER_ADMIN: 100,
    Role.ADMIN: 90,
    Role.FARM_ADMIN: 70,
    Role.FARM_MANAGER: 50,
    Role.FARM_SUPERVISOR: 40,
    Role.VET: 30,
    Role.FARM_HAND: 20,
    Role.CUSTOMER: 10,
}
_SINGLE_FARM_OWNER_RANK = 80   # FARMER owning a single-farm tenant
_COOPERATIVE_MEMBER_RANK = 60  # FARMER who is a member of a cooperative
_MIN_RESETTER_RANK = 70


def _rank(user: User) -> int:
    role = (user.role or '').strip().upper()
    if role == Role.FARMER:
        tenant_type = normalize_tenant_type(getattr(user.tenant, 'tenant_type', None))
        return _SINGLE_FARM_OWNER_RANK if tenant_type == 'single' else _COOPERATIVE_MEMBER_RANK
    return _ROLE_RANK.get(role, 0)


class AdminPasswordResetService:
    @staticmethod
    def authorize(actor: User, target: User) -> None:
        actor_rank = _rank(actor)
        if actor_rank < _MIN_RESETTER_RANK:
            raise AuthError('FORBIDDEN', 'Member administration access is required.', 403)
        if actor.role != Role.SUPER_ADMIN and target.tenant_id != actor.tenant_id:
            # Indistinguishable from a missing user.
            raise AuthError('NOT_FOUND', 'User not found.', 404)
        if target.id == actor.id:
            raise AuthError('FORBIDDEN_TARGET', 'Use forgot password to reset your own password.', 403)
        if target.role == Role.SUPER_ADMIN or _rank(target) >= actor_rank:
            raise AuthError('FORBIDDEN_TARGET', 'You cannot reset the password for this user.', 403)

    @staticmethod
    def issue(actor: User, target_user_id: int, *, ip_address=None) -> dict:
        target = UserRepository.get_by_id(target_user_id)
        if not target:
            raise AuthError('NOT_FOUND', 'User not found.', 404)
        AdminPasswordResetService.authorize(actor, target)
        if not target.is_active:
            raise AuthError('FORBIDDEN_TARGET', 'This account is not active. Send an account invitation instead.', 403)

        link = PasswordResetLinkService.issue(
            target, channel='admin', target=target.phone_number or target.username,
            created_by_id=actor.id, ip_address=ip_address,
        )
        SessionService.revoke_all_sessions(target)
        record_audit(
            user_id=actor.id,
            action='ADMIN_PASSWORD_RESET',
            entity_type='User',
            entity_id=target.id,
            old_value={},
            new_value={'reset_link_issued': True, 'sessions_revoked': True},
            ip_address=ip_address,
        )
        db.session.commit()

        return {
            'message': 'Reset link created. Share it with the user directly.',
            'user': {'id': target.id, 'name': target.name or target.username},
            'reset_url': link.url,
            'expires_at': link.challenge.expires_at.isoformat(),
            'expires_in_seconds': int(VerificationChallengeService.ttl().total_seconds()),
        }
