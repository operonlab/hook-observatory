"""Authentication routes — register, login, logout, session check, OAuth."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from src.config import settings
from src.events.bus import Event, event_bus
from src.events.types import AuthEvents
from src.shared.deps import get_db
from src.shared.errors import BadRequestError
from src.shared.redis import get_redis

from .deps import get_current_user
from .models import User
from .oauth import oauth
from .schemas import PreferencesUpdate, SessionResponse, UserCreate, UserLogin
from .services import user_service

router = APIRouter(tags=["auth"])


async def _create_session(request: Request, db: AsyncSession, user: User) -> None:
    """Create Redis-backed session and write signed cookie via middleware."""
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

    request.state.session["token"] = token
    request.state.user = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
    }
    request.state._session_modified = True


# --- Email/Password auth ---


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.register(db, body.email, body.password, body.name)
    await db.commit()

    await _create_session(request, db, user)

    await event_bus.publish(
        Event(
            type=AuthEvents.USER_REGISTERED,
            data={"email": body.email, "name": body.name},
            source="auth",
            user_id=user.id,
        )
    )

    return {"user": user_service.to_response(user)}


@router.post("/login")
async def login(
    body: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.authenticate(db, body.email, body.password)
    if not user:
        raise BadRequestError("Invalid credentials", code="auth.invalid_credentials")

    await db.commit()
    await _create_session(request, db, user)

    await event_bus.publish(
        Event(
            type=AuthEvents.USER_LOGGED_IN,
            data={"email": body.email},
            source="auth",
            user_id=user.id,
        )
    )

    return {"user": user_service.to_response(user)}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    user = getattr(request.state, "user", None)
    user_id = user["id"] if user else None

    # Revoke Redis session
    token = request.state.session.get("token")
    if token:
        redis = get_redis()
        try:
            await user_service.revoke_session(db, redis, token)
            await db.commit()
        finally:
            await redis.aclose()

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


# --- Preferences ---


@router.get("/me/preferences")
async def get_preferences(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = get_current_user(request)
    return await user_service.get_preferences(db, user["id"])


@router.patch("/me/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = get_current_user(request)
    patch = body.model_dump(exclude_none=True)
    result = await user_service.update_preferences(db, user["id"], patch)
    await db.commit()
    return result


# --- OAuth routes ---


@router.get("/login/google")
async def oauth_google(request: Request):
    """Initiate Google OAuth flow."""
    redirect_uri = f"{settings.oauth_redirect_base}/auth/callback/google"
    request.session["oauth_redirect"] = request.query_params.get("redirect", "/")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback/google")
async def oauth_google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback."""
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        raise BadRequestError("Failed to get user info from Google", code="auth.oauth_failed")

    user, is_new = await user_service.get_or_create_oauth_user(
        db,
        provider="google",
        provider_id=userinfo["sub"],
        email=userinfo.get("email"),
        name=userinfo.get("name"),
        avatar_url=userinfo.get("picture"),
        raw_data=dict(userinfo),
    )
    await db.commit()

    await _create_session(request, db, user)

    event_type = AuthEvents.USER_REGISTERED if is_new else AuthEvents.USER_LOGGED_IN
    await event_bus.publish(
        Event(
            type=event_type,
            data={"email": user.email, "provider": "google"},
            source="auth",
            user_id=user.id,
        )
    )

    redirect = request.session.pop("oauth_redirect", "/")
    return RedirectResponse(url=redirect)


@router.get("/login/github")
async def oauth_github(request: Request):
    """Initiate GitHub OAuth flow."""
    redirect_uri = f"{settings.oauth_redirect_base}/auth/callback/github"
    request.session["oauth_redirect"] = request.query_params.get("redirect", "/")
    return await oauth.github.authorize_redirect(request, redirect_uri)


@router.get("/callback/github")
async def oauth_github_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle GitHub OAuth callback."""
    token = await oauth.github.authorize_access_token(request)
    resp = await oauth.github.get("user", token=token)
    profile = resp.json()

    # Get primary email if not public
    email = profile.get("email")
    if not email:
        emails_resp = await oauth.github.get("user/emails", token=token)
        emails = emails_resp.json()
        primary = next((e for e in emails if e.get("primary")), None)
        if primary:
            email = primary["email"]

    user, is_new = await user_service.get_or_create_oauth_user(
        db,
        provider="github",
        provider_id=str(profile["id"]),
        email=email,
        name=profile.get("name") or profile.get("login"),
        avatar_url=profile.get("avatar_url"),
        raw_data=profile,
    )
    await db.commit()

    await _create_session(request, db, user)

    event_type = AuthEvents.USER_REGISTERED if is_new else AuthEvents.USER_LOGGED_IN
    await event_bus.publish(
        Event(
            type=event_type,
            data={"email": user.email, "provider": "github"},
            source="auth",
            user_id=user.id,
        )
    )

    redirect = request.session.pop("oauth_redirect", "/")
    return RedirectResponse(url=redirect)
