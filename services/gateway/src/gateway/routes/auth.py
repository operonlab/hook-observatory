"""Authentication routes — register, login, logout, session check."""

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, status

from gateway.config import settings
from gateway.deps import hash_password, verify_password, get_current_user
from gateway.models.schemas import (
    UserCreate,
    UserLogin,
    UserResponse,
    SessionResponse,
)

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# In-memory user store (MVP) — keyed by email
# Each value: {id, email, name, role, status, password_hash, password_salt, created_at}
# ---------------------------------------------------------------------------
_users: dict[str, dict] = {}


def _user_to_response(u: dict) -> UserResponse:
    return UserResponse(
        id=u["id"],
        email=u["email"],
        name=u["name"],
        role=u["role"],
        status=u["status"],
        created_at=u["created_at"],
    )


def _set_session(request: Request, user_dict: dict) -> None:
    """Write user info into the session (triggers cookie write)."""
    request.state.session["user"] = {
        "id": user_dict["id"],
        "email": user_dict["email"],
        "name": user_dict["name"],
        "role": user_dict["role"],
        "status": user_dict["status"],
    }
    request.state.user = request.state.session["user"]
    request.state._session_modified = True


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, request: Request):
    if body.email in _users:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    pw_hash, pw_salt = hash_password(body.password)
    user = {
        "id": uuid.uuid4().hex,
        "email": body.email,
        "name": body.name,
        "role": "user",
        "status": "active",
        "password_hash": pw_hash,
        "password_salt": pw_salt,
        "created_at": datetime.now(timezone.utc),
    }
    _users[body.email] = user

    _set_session(request, user)
    return {"user": _user_to_response(user)}


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------
@router.post("/login")
async def login(body: UserLogin, request: Request):
    user = _users.get(body.email)
    if not user or not verify_password(body.password, user["password_hash"], user["password_salt"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _set_session(request, user)
    return {"user": _user_to_response(user)}


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request):
    request.state.session = {}
    request.state.user = None
    request.state._session_cleared = True


# ---------------------------------------------------------------------------
# GET /auth/session
# ---------------------------------------------------------------------------
@router.get("/session", response_model=SessionResponse)
async def session_info(request: Request):
    user = get_current_user(request)

    # Look up full user record for created_at
    full_user = _users.get(user["email"])
    if not full_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.session_max_age)
    return SessionResponse(
        user=_user_to_response(full_user),
        expires_at=expires_at,
    )
