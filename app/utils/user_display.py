from __future__ import annotations

from typing import Optional

from app.models.user import Role
from app.repositories.user_repo import UserRepository

ROLE_LABELS = {
    Role.FARMER: 'Farm owner',
    Role.ADMIN: 'Admin',
    Role.SUPER_ADMIN: 'Admin',
    Role.FARM_ADMIN: 'Farm admin',
    Role.FARM_MANAGER: 'Farm manager',
    Role.FARM_SUPERVISOR: 'Supervisor',
    Role.FARM_HAND: 'Farm hand',
    Role.VET: 'Vet',
    Role.CUSTOMER: 'Customer',
}


def display_name(user_id: Optional[int]) -> Optional[str]:
    """The name to show for a user id, or None when there is no such user."""
    user = UserRepository.get_by_id(user_id) if user_id else None
    if not user:
        return None
    if user.name and user.name.strip():
        return user.name.strip()
    # Phone sign-ups get their number as username; never show that as a name.
    if user.username and not user.username.isdigit():
        return user.username
    return ROLE_LABELS.get(user.role, 'Team member')
