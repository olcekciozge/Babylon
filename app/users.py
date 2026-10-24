from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, password_hasher
from app.database import get_db
from app.models import User
from app.presence import presence

router = APIRouter(prefix="/api/users", tags=["users"])


class ProfileUpdate(BaseModel):
    bio: str = Field(max_length=160)
    # Hex color like #6366f1
    avatar_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class UsernameUpdate(BaseModel):
    new_username: str = Field(pattern=r"^[A-Za-z0-9_]{3,20}$")
    password: str  # current password, required for this sensitive change

class VisibilityUpdate(BaseModel):
    show_online: bool

def profile_data(user: User, include_private: bool = False) -> dict:
    data = {
        "username": user.username,
        "bio": user.bio,
        "avatar_color": user.avatar_color,
        "created_at": user.created_at.isoformat(),
    }
    if include_private:
        data["show_online"] = user.show_online
    return data


# NOTE: "/me" routes must be declared BEFORE "/{username}",
# otherwise FastAPI would treat "me" as a username.
@router.get("/me")
def get_my_profile(user: User = Depends(get_current_user)):
    return profile_data(user, include_private=True)


@router.put("/me")
def update_my_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.bio = data.bio.strip()
    user.avatar_color = data.avatar_color
    db.commit()
    return profile_data(user)


@router.put("/me/username")
def change_username(
    data: UsernameUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not password_hasher.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Exclude the user themselves, so "alice" -> "Alice" (only casing) is allowed
    taken = db.scalar(
        select(User).where(
            User.username_lower == data.new_username.lower(), User.id != user.id
        )
    )
    if taken:
        raise HTTPException(status_code=409, detail="Username is already taken")

    user.username = data.new_username
    user.username_lower = data.new_username.lower()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username is already taken")
    return profile_data(user)

@router.put("/me/visibility")
async def set_visibility(
    data: VisibilityUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changed = user.show_online != data.show_online
    user.show_online = data.show_online
    db.commit()
    # Friends should see the change immediately, without waiting for a reconnect
    if changed and presence.is_online(user.id):
        await presence.notify_friends(user.id, data.show_online)
    return {"show_online": user.show_online}

@router.get("/{username}")
def get_user_profile(
    username: str,
    _: User = Depends(get_current_user),  # only logged-in users can view profiles
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username_lower == username.lower()))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return profile_data(user)