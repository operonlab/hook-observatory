"""Authentication routes — register, login, logout, session, OAuth, admin."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.events.bus import Event, event_bus
from src.events.types import AuthEvents
from src.shared.deps import get_db
from src.shared.errors import BadRequestError
from src.shared.redis import get_redis
from src.shared.schemas import PaginatedResponse

from .deps import get_current_user
from .schemas import (
    SessionResponse,
    UserCreate,
    UserDetailResponse,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from .services import user_service

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_session_and_set_cookie(
    request: Request,
    user,
    db: AsyncSession,
) -> str:
    """Create Redis-backed session and set cookie on request state."""
    redis = get_redis()
    try:
        token = await user_service.create_session(
            db,
            redis,
            user,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    finally:
        await redis.aclose()

    request.state.session = {"token": token}
    request.state._session_modified = True
    return token


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.register(db, body.email, body.password, body.name)
    await db.commit()

    await _create_session_and_set_cookie(request, user, db)
    await db.commit()

    await event_bus.publish(
        Event(
            type=AuthEvents.USER_REGISTERED,
            data={"email": body.email, "name": body.name},
            source="auth",
            user_id=user.id,
        )
    )

    return {"user": user_service.to_response(user)}


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
@router.post("/login")
async def login(
    body: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.authenticate(db, body.email, body.password)
    if not user:
        raise BadRequestError("Invalid credentials", code="auth.invalid_credentials")

    if user.status != "active":
        raise BadRequestError(
            "Account is not active", code="auth.account_not_active"
        )

    await _create_session_and_set_cookie(request, user, db)
    await db.commit()

    await event_bus.publish(
        Event(
            type=AuthEvents.USER_LOGGED_IN,
            data={"email": body.email},
            source="auth",
            user_id=user.id,
        )
    )

    return {"user": user_service.to_response(user)}


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    user = getattr(request.state, "user", None)
    user_id = user["id"] if user else None
    token = request.state.session.get("token") if request.state.session else None

    if token:
        redis = get_redis()
        try:
            await user_service.revoke_session(db, redis, token)
        finally:
            await redis.aclose()
        await db.commit()

    request.state.session = {}
    request.state.user = None
    request.state._session_cleared = True

    await event_bus.publish(
        Event(
            type=AuthEvents.USER_LOGGED_OUT,
            data={},
            source="auth",
            user_id=user_id,
        )
    )


# ---------------------------------------------------------------------------
# GET /session
# ---------------------------------------------------------------------------
@router.get("/session", response_model=SessionResponse)
async def session_info(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_user = get_current_user(request)

    user = await user_service.get_by_id(db, session_user["id"])
    if not user:
        raise BadRequestError("User not found", code="auth.user_not_found")

    expires_at = datetime.now(UTC) + timedelta(seconds=settings.session_max_age)
    return SessionResponse(
        user=user_service.to_response(user),
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------
@router.get("/me", response_model=UserDetailResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session_user = get_current_user(request)
    user = await user_service.get_by_id(db, session_user["id"])
    if not user:
        raise BadRequestError("User not found", code="auth.user_not_found")

    oauth_accounts = await user_service.get_oauth_accounts(db, user.id)
    return user_service.to_detail_response(user, oauth_accounts)


# ---------------------------------------------------------------------------
# OAuth endpoints
# ---------------------------------------------------------------------------


@router.get("/oauth/{provider}")
async def oauth_redirect(provider: str, request: Request):
    """Redirect to OAuth provider's authorization page."""
    from .oauth import oauth

    client = oauth.create_client(provider)
    if not client:
        raise BadRequestError(
            f"OAuth provider '{provider}' is not configured",
            code="auth.oauth_not_configured",
        )

    redirect_uri = f"{settings.oauth_redirect_base}/auth/oauth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback: create/link user, set session."""
    from authlib.integrations.base_client import OAuthError

    from .oauth import oauth

    client = oauth.create_client(provider)
    if not client:
        raise BadRequestError(
            f"OAuth provider '{provider}' is not configured",
            code="auth.oauth_not_configured",
        )

    # authorize_access_token verifies the state parameter against request.session
    # (provided by Starlette SessionMiddleware). Raises OAuthError on CSRF mismatch.
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        raise BadRequestError(
            f"OAuth error: {exc.description or exc.error}",
            code="auth.oauth_state_error",
        ) from exc

    # Extract user info based on provider
    if provider == "google":
        user_info = token.get("userinfo", {})
        provider_id = user_info.get("sub", "")
        email = user_info.get("email")
        name = user_info.get("name")
        avatar_url = user_info.get("picture")
    elif provider == "github":
        resp = await client.get("user", token=token)
        user_info = resp.json()
        provider_id = str(user_info.get("id", ""))
        email = user_info.get("email")
        name = user_info.get("name") or user_info.get("login")
        avatar_url = user_info.get("avatar_url")

        # GitHub may not return email in profile — fetch from emails API
        if not email:
            emails_resp = await client.get("user/emails", token=token)
            emails = emails_resp.json()
            primary = next((e for e in emails if e.get("primary")), None)
            if primary:
                email = primary["email"]
    else:
        raise BadRequestError(
            f"Unsupported provider: {provider}",
            code="auth.unsupported_provider",
        )

    # Validate provider_id is not empty
    if not provider_id:
        raise BadRequestError(
            "OAuth provider returned empty user ID",
            code="auth.oauth_empty_provider_id",
        )

    user, is_new = await user_service.get_or_create_oauth_user(
        db,
        provider=provider,
        provider_id=provider_id,
        email=email,
        name=name,
        avatar_url=avatar_url,
        raw_data=user_info,
    )

    await _create_session_and_set_cookie(request, user, db)
    await db.commit()

    event_type = AuthEvents.USER_REGISTERED if is_new else AuthEvents.USER_LOGGED_IN
    await event_bus.publish(
        Event(
            type=event_type,
            data={"provider": provider, "email": email},
            source="auth",
            user_id=user.id,
        )
    )

    await event_bus.publish(
        Event(
            type=AuthEvents.OAUTH_LINKED,
            data={"provider": provider, "provider_id": provider_id},
            source="auth",
            user_id=user.id,
        )
    )

    # Redirect to frontend
    return RedirectResponse(url="/apps", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Admin endpoints (require admin role)
# ---------------------------------------------------------------------------


@router.get("/admin/users")
async def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)."""
    current = get_current_user(request)
    if current.get("role") != "admin":
        from src.shared.errors import ForbiddenError

        raise ForbiddenError("Admin access required", code="auth.admin_required")

    users, total = await user_service.list_users(
        db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        search=search,
    )
    return PaginatedResponse(
        items=[user_service.to_response(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/admin/users/{user_id}", response_model=UserDetailResponse)
async def get_user_detail(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get user detail with OAuth accounts (admin only)."""
    current = get_current_user(request)
    if current.get("role") != "admin":
        from src.shared.errors import ForbiddenError

        raise ForbiddenError("Admin access required", code="auth.admin_required")

    user = await user_service.get_by_id(db, user_id)
    if not user:
        from src.shared.errors import NotFoundError

        raise NotFoundError("User not found", code="auth.user_not_found")

    oauth_accounts = await user_service.get_oauth_accounts(db, user.id)
    return user_service.to_detail_response(user, oauth_accounts)


@router.patch("/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update user role/status (admin only)."""
    current = get_current_user(request)
    if current.get("role") != "admin":
        from src.shared.errors import ForbiddenError

        raise ForbiddenError("Admin access required", code="auth.admin_required")

    old_user = await user_service.get_by_id(db, user_id)
    if not old_user:
        from src.shared.errors import NotFoundError

        raise NotFoundError("User not found", code="auth.user_not_found")

    old_role = old_user.role
    old_status = old_user.status

    user = await user_service.update_user(
        db,
        user_id,
        display_name=body.display_name,
        role=body.role,
        status=body.status,
    )
    await db.commit()

    # Publish events for role/status changes
    if body.role and body.role != old_role:
        await event_bus.publish(
            Event(
                type=AuthEvents.ROLE_ASSIGNED,
                data={"old_role": old_role, "new_role": body.role},
                source="auth",
                user_id=user_id,
            )
        )

    if body.status and body.status != old_status:
        await event_bus.publish(
            Event(
                type=AuthEvents.USER_STATUS_CHANGED,
                data={"old_status": old_status, "new_status": body.status},
                source="auth",
                user_id=user_id,
            )
        )

        # If suspended/banned → revoke all sessions
        if body.status in ("suspended", "banned"):
            redis = get_redis()
            try:
                await user_service.revoke_all_sessions(db, redis, user_id)
                await db.commit()
            finally:
                await redis.aclose()

    return user_service.to_response(user)
