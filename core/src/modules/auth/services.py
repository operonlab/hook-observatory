"""Auth services — user registration, authentication, OAuth, session management.

This is the PUBLIC API of the auth module.
"""

import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.shared.errors import BadRequestError, ConflictError, NotFoundError
from src.shared.fsm import validate_transition

from .deps import hash_password, verify_password
from .lifecycle import UserLifecycle
from .models import OAuthAccount, Session, User
from .schemas import OAuthAccountResponse, UserDetailResponse, UserResponse

logger = logging.getLogger(__name__)


class UserService:
    """User CRUD + authentication + OAuth logic."""

    def to_response(self, user: User) -> UserResponse:
        return UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
        )

    def to_detail_response(
        self, user: User, oauth_accounts: list[OAuthAccount]
    ) -> UserDetailResponse:
        return UserDetailResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            role=user.role,
            status=user.status,
            created_at=user.created_at,
            oauth_accounts=[
                OAuthAccountResponse(
                    id=oa.id,
                    provider=oa.provider,
                    provider_id=oa.provider_id,
                    email=oa.email,
                    name=oa.name,
                    avatar_url=oa.avatar_url,
                    created_at=oa.created_at,
                )
                for oa in oauth_accounts
            ],
        )

    # --- User lookups ---

    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        q = select(User).where(User.email == email)
        return (await db.execute(q)).scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, user_id: str) -> User | None:
        return await db.get(User, user_id)

    # --- Registration ---

    async def register(self, db: AsyncSession, email: str, password: str, name: str) -> User:
        existing = await self.get_by_email(db, email)
        if existing:
            raise ConflictError("Email already registered", code="auth.email_conflict")

        user = User(
            email=email,
            display_name=name,
            password_hash=hash_password(password),
            status="pending",
        )
        db.add(user)
        await db.flush()
        return user

    # --- Authentication ---

    async def authenticate(self, db: AsyncSession, email: str, password: str) -> User | None:
        """Verify credentials. Returns User if valid, None otherwise."""
        user = await self.get_by_email(db, email)
        if not user or not user.password_hash:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    # --- OAuth ---

    async def get_or_create_oauth_user(
        self,
        db: AsyncSession,
        provider: str,
        provider_id: str,
        email: str | None,
        name: str | None,
        avatar_url: str | None,
        raw_data: dict | None,
    ) -> tuple[User, bool]:
        """OAuth login: find or create user + link OAuthAccount.

        Returns (user, is_new_user).
        """
        # 1. Check existing OAuth link
        q = select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_id == provider_id,
        )
        oauth_account = (await db.execute(q)).scalar_one_or_none()
        if oauth_account:
            user = await db.get(User, oauth_account.user_id)
            if not user:
                raise NotFoundError("Linked user not found", code="auth.user_not_found")
            return user, False

        # 2. Check existing user by email (auto-link)
        user: User | None = None
        is_new = False
        if email:
            user = await self.get_by_email(db, email)

        # 3. Create new user if needed
        if not user:
            user = User(
                email=email or f"{provider}_{provider_id}@oauth.local",
                display_name=name or provider_id,
                avatar_url=avatar_url,
                role="user",
                status="active",
            )
            db.add(user)
            await db.flush()
            is_new = True

        # 4. Create OAuth link
        oauth = OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_id=provider_id,
            email=email,
            name=name,
            avatar_url=avatar_url,
            raw_data=raw_data,
        )
        db.add(oauth)
        await db.flush()

        return user, is_new

    async def get_oauth_accounts(self, db: AsyncSession, user_id: str) -> list[OAuthAccount]:
        q = select(OAuthAccount).where(OAuthAccount.user_id == user_id)
        return list((await db.execute(q)).scalars().all())

    # --- Session management ---

    async def create_session(
        self,
        db: AsyncSession,
        redis,
        user: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        """Create DB session + Redis cache. Returns session token."""
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.session_max_age)

        # DB record
        session = Session(
            user_id=user.id,
            token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
        )
        db.add(session)
        await db.flush()

        # Redis cache
        user_data = {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "status": user.status,
            "avatar_url": user.avatar_url,
        }
        try:
            await redis.set(
                f"auth:session:{token_hash}",
                json.dumps(user_data),
                ex=settings.session_max_age,
            )
        except Exception:
            logger.warning(
                "Redis session write failed — session won't persist in cache",
                exc_info=True,
            )

        return token

    async def validate_session(self, redis, token: str) -> dict | None:
        """Validate session token via Redis. Returns user dict or None."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        data = await redis.get(f"auth:session:{token_hash}")
        if not data:
            return None
        return json.loads(data)

    async def revoke_session(self, db: AsyncSession, redis, token: str) -> None:
        """Revoke a single session (logout)."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        await redis.delete(f"auth:session:{token_hash}")
        await db.execute(delete(Session).where(Session.token_hash == token_hash))
        await db.flush()

    async def revoke_all_sessions(self, db: AsyncSession, redis, user_id: str) -> int:
        """Revoke all sessions for a user (status change). Returns count."""
        q = select(Session).where(Session.user_id == user_id)
        sessions = (await db.execute(q)).scalars().all()
        count = 0
        for s in sessions:
            try:
                await redis.delete(f"auth:session:{s.token_hash}")
            except Exception:
                logger.warning(
                    "Redis session revoke failed for token_hash=%s",
                    s.token_hash,
                    exc_info=True,
                )
            count += 1
        await db.execute(delete(Session).where(Session.user_id == user_id))
        await db.flush()
        return count

    # --- Preferences ---

    async def get_preferences(self, db: AsyncSession, user_id: str) -> dict:
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError("User not found", code="auth.user_not_found")
        return user.preferences or {}

    async def update_preferences(self, db: AsyncSession, user_id: str, patch: dict) -> dict:
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError("User not found", code="auth.user_not_found")
        merged = {**(user.preferences or {}), **patch}
        user.preferences = merged
        await db.flush()
        return merged

    # --- Admin operations ---

    async def list_users(
        self,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        """List users with optional filters. Returns (users, total)."""
        base = select(User)
        count_base = select(func.count()).select_from(User)

        if status_filter:
            base = base.where(User.status == status_filter)
            count_base = count_base.where(User.status == status_filter)

        if search:
            # Escape ILIKE special characters to prevent wildcard injection
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            base = base.where(User.email.ilike(pattern) | User.display_name.ilike(pattern))
            count_base = count_base.where(
                User.email.ilike(pattern) | User.display_name.ilike(pattern)
            )

        total = (await db.execute(count_base)).scalar_one()
        q = base.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        users = list((await db.execute(q)).scalars().all())
        return users, total

    async def update_user(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        display_name: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> User:
        """Update user fields. Validates role/status values."""
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError("User not found", code="auth.user_not_found")

        if display_name is not None:
            user.display_name = display_name
        if role is not None:
            if role not in ("admin", "user", "guest"):
                raise BadRequestError(f"Invalid role: {role}", code="auth.invalid_role")
            user.role = role
        if status is not None:
            if status not in ("pending", "active", "suspended", "banned"):
                raise BadRequestError(f"Invalid status: {status}", code="auth.invalid_status")
            validate_transition(UserLifecycle, user.status, status, "user")
            old_status = user.status
            user.status = status

        await db.flush()
        await db.refresh(user)

        if status is not None and old_status != status:
            from .store import StateTransitioned, auth_store

            await auth_store.dispatch(
                StateTransitioned(
                    module="auth",
                    entity_type="user",
                    entity_id=str(user.id),
                    old_state=old_status,
                    new_state=status,
                )
            )

        return user


user_service = UserService()
