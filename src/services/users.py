"""Identity mapping: turn validated OIDC claims into a local ``User`` row."""

from __future__ import annotations

from sqlalchemy import select

from src.backend.constants import ROLE_CUSTOMER
from src.backend.models import User


def get_or_create_user(
    session,
    *,
    sub: str,
    email: str | None,
    name: str,
    role: str | None = None,
) -> User:
    """Upsert a user keyed by the stable ``sub`` claim.

    ``role`` is derived from validated claims upstream; when it is not supplied
    (e.g. a direct test override) it defaults to customer rather than trusting
    any request-supplied value.
    """
    user = session.execute(select(User).where(User.sub == sub)).scalar_one_or_none()
    effective_role = role or ROLE_CUSTOMER
    if user is None:
        user = User(sub=sub, email=email, name=name, role=effective_role)
        session.add(user)
        session.flush()
        return user

    changed = False
    if email is not None and user.email != email:
        user.email = email
        changed = True
    if name and user.name != name:
        user.name = name
        changed = True
    if effective_role != user.role:
        user.role = effective_role
        changed = True
    if changed:
        session.flush()
    return user
