from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Message, Room, RoomMember, User

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class RoomCreate(BaseModel):
    # 3-30 characters: letters, digits, spaces, hyphen, underscore
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\- ]{2,29}$")


def iso(dt: datetime) -> str:
    """SQLite stores naive UTC datetimes. The 'Z' tells the browser it is UTC."""
    return dt.replace(tzinfo=None).isoformat() + "Z"


def is_member(db: Session, user_id: int, room_id: int) -> bool:
    return db.get(RoomMember, (user_id, room_id)) is not None


def room_data(room: Room, member_count: int, joined: bool) -> dict:
    return {"id": room.id, "name": room.name, "member_count": member_count, "is_member": joined}


@router.get("")
def list_rooms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(RoomMember.room_id, func.count()).group_by(RoomMember.room_id)
        ).all()
    )
    mine = set(db.scalars(select(RoomMember.room_id).where(RoomMember.user_id == user.id)))
    rooms = db.scalars(select(Room).order_by(Room.name_lower)).all()
    return [room_data(r, counts.get(r.id, 0), r.id in mine) for r in rooms]


@router.post("", status_code=201)
def create_room(
    data: RoomCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    name = data.name.strip()
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="Room name must be at least 3 characters")
    if db.scalar(select(Room).where(Room.name_lower == name.lower())):
        raise HTTPException(status_code=409, detail="Room name is already taken")

    room = Room(name=name, name_lower=name.lower())
    db.add(room)
    try:
        db.flush()  # assigns room.id without committing yet
        db.add(RoomMember(user_id=user.id, room_id=room.id))  # creator joins automatically
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room name is already taken")
    return room_data(room, 1, True)


@router.post("/{room_id}/join")
def join_room(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if db.get(Room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if not is_member(db, user.id, room_id):
        db.add(RoomMember(user_id=user.id, room_id=room_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # joined twice at the same moment, which is fine
    return {"joined": True}


@router.delete("/{room_id}/leave")
def leave_room(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    membership = db.get(RoomMember, (user.id, room_id))
    if membership:
        db.delete(membership)
        db.commit()
    return {"left": True}


@router.get("/{room_id}/messages")
def get_messages(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not is_member(db, user.id, room_id):
        raise HTTPException(status_code=403, detail="Join the room to read its messages")

    # Newest 50 first, then reversed so the oldest of them comes first
    rows = db.scalars(
        select(Message).where(Message.room_id == room_id).order_by(Message.id.desc()).limit(50)
    ).all()
    rows.reverse()
    return [
        {
            "username": m.user.username,
            "avatar_color": m.user.avatar_color,
            "text": m.text,
            "created_at": iso(m.created_at),
        }
        for m in rows
    ]