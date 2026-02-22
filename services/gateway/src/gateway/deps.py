"""Shared dependencies — password hashing, auth helpers."""

import hashlib
import os
import secrets

from fastapi import HTTPException, Request, status


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Hash a password with PBKDF2-HMAC-SHA256.

    Returns (hex_hash, hex_salt).
    """
    if salt is None:
        salt = os.urandom(32)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)

    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations=600_000)
    return dk.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """Verify a password against a stored hash+salt."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        bytes.fromhex(stored_salt),
        iterations=600_000,
    )
    return secrets.compare_digest(dk.hex(), stored_hash)


def get_current_user(request: Request) -> dict:
    """Extract authenticated user from request state; raise 401 if absent."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user
