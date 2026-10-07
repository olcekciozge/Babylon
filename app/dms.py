from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.friends import find_relation, person
from app.models import DirectChat, Room, RoomMember, User

router = APIRouter(prefix="/api/dms", tags=["dms"])


def are_friends(db: Session, a: int, b: int) -> bool:
    relation = find_relation(db, a, b)
    return relation is not None and relation.status == "accepted"


def find_chat(db: Session, a: int, b: int) -> DirectChat | None:
    low, high = sorted((a, b))
    return db.scalar(
        select(DirectChat).where(DirectChat.user_a_id == low, DirectChat.user_b_id == high)
    )


@router.get("")
def list_dms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """My private chats, but only with people who are still my friends."""
    chats = db.scalars(
        select(DirectChat).where(
            or_(DirectChat.user_a_id == user.id, DirectChat.user_b_id == user.id)
        )
    ).all()
    result = []
    for chat in chats:
        other_id = chat.user_b_id if chat.user_a_id == user.id else chat.user_a_id
        other = db.get(User, other_id)
        if other and are_friends(db, user.id, other_id):
            result.append({"room_id": chat.room_id, "user": person(other)})
    result.sort(key=lambda d: d["user"]["username"].lower())
    return result


@router.post("/{user_id}")
def open_dm(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Opens the private chat with a friend, creating it the first time."""
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="You can't message yourself")
    other = db.get(User, user_id)
    if other is None or not are_friends(db, user.id, user_id):
        raise HTTPException(status_code=403, detail="You can only message your friends")

    chat = find_chat(db, user.id, user_id)
    if chat is None:
        low, high = sorted((user.id, user_id))
        # The ":" can't appear in names users choose (see RoomCreate), so this name never collides
        name = f"dm:{low}:{high}"
        room = Room(name=name, name_lower=name, owner_id=low)
        db.add(room)
        try:
            db.flush()
            db.add_all([
                RoomMember(user_id=low, room_id=room.id),
                RoomMember(user_id=high, room_id=room.id),
                DirectChat(room_id=room.id, user_a_id=low, user_b_id=high),
            ])
            db.commit()
            return {"room_id": room.id, "user": person(other)}
        except IntegrityError:
            db.rollback()  # the other person opened it at the same moment
            chat = find_chat(db, user.id, user_id)
            if chat is None:
                raise
    return {"room_id": chat.room_id, "user": person(other)}