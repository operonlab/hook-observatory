"""Auth dependencies — password hashing (argon2id), auth helpers."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, status

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash password with Argon2id. Returns encoded hash (contains embedded salt)."""
    return _ph.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against Argon2id hash."""
    try:
        return _ph.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


def get_current_user(request: Request) -> dict:
    """Extract authenticated user from request state; raise 401/403 if absent or inactive."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    if user.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )
    return user
