import jwt
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db
from .models import User

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    if len(password) < 14:
        raise ValueError("Password must be at least 14 characters.")
    return _hasher.hash(password)

def verify_password(password: str, digest: str) -> bool:
    try:
        return _hasher.verify(digest, password)
    except (VerifyMismatchError, Exception):
        return False

def create_access_token(user: User):
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": user.id, "role": user.role, "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access"
    }, settings.jwt_secret, algorithm="HS256")

async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db)
):
    token = credentials.credentials if credentials else request.cookies.get("qoe_access")
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError("wrong token type")
    except Exception:
        raise HTTPException(401, "Invalid or expired access token")
    user = await db.get(User, payload.get("sub"))
    if not user or not user.active:
        raise HTTPException(401, "Account is inactive")
    return user

async def admin_user(user: User = Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator role required")
    return user
