import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pwdlib import PasswordHash
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User

# In production this comes from an environment variable, never from the code
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me-please-use-env-var")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

password_hasher = PasswordHash.recommended()  # Argon2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    # 3-20 characters: letters, digits and underscore only
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,20}$")
    password: str = Field(min_length=8, max_length=128)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    # "sub" (subject) must be a string in PyJWT
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_user_from_token(token: str, db: Session) -> User | None:
    """Returns the user a token belongs to, or None if the token is invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return db.get(User, int(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    user = get_user_from_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.post("/register", status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    taken = db.scalar(select(User).where(User.username_lower == data.username.lower()))
    if taken:
        raise HTTPException(status_code=409, detail="Username is already taken")

    user = User(
        username=data.username,
        username_lower=data.username.lower(),
        password_hash=password_hasher.hash(data.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two people registered the same name at the same moment
        db.rollback()
        raise HTTPException(status_code=409, detail="Username is already taken")
    return {"id": user.id, "username": user.username}


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username_lower == form.username.lower()))
    # Same error for "no such user" and "wrong password" so attackers can't tell which
    if user is None or not password_hasher.verify(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username}