from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.manager import manager
from app.models import DirectChat, JoinRequest, Message, ReadState, Room, RoomMember, User
from app.presence import presence

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class RoomCreate(BaseModel):
    # 3-30 characters: letters, digits, spaces, hyphen, underscore
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\- ]{2,29}$")


class DescriptionUpdate(BaseModel):
    description: str = Field(max_length=200)


# ---------- Helpers ----------
def iso(dt: datetime) -> str:
    """SQLite stores naive UTC datetimes. The 'Z' tells the browser it is UTC."""
    return dt.replace(tzinfo=None).isoformat() + "Z"


def is_member(db: Session, user_id: int, room_id: int) -> bool:
    return db.get(RoomMember, (user_id, room_id)) is not None


def is_direct(db: Session, room_id: int) -> bool:
    """Private chats between two friends are stored as hidden rooms."""
    return db.get(DirectChat, room_id) is not None


def get_owned_room(db: Session, room_id: int, user: User) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    if is_direct(db, room_id):
        raise HTTPException(status_code=400, detail="Private chats can't be changed")
    if room.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the room owner can do this")
    return room


def member_counts(db: Session) -> dict[int, int]:
    return dict(
        db.execute(select(RoomMember.room_id, func.count()).group_by(RoomMember.room_id)).all()
    )


def is_shown_online(viewer_id: int, user_id: int, show_online: bool) -> bool:
    """The viewer always counts as online (they are using the app right now).
    Everyone else counts only if connected AND they allow others to see it."""
    return user_id == viewer_id or presence.visible_online(user_id, show_online)


def online_counts(db: Session, room_ids: list[int], viewer_id: int) -> dict[int, int]:
    """How many members of each room are online."""
    if not room_ids:
        return {}
    rows = db.execute(
        select(RoomMember.room_id, User.id, User.show_online)
        .select_from(RoomMember)
        .join(User, User.id == RoomMember.user_id)
        .where(RoomMember.room_id.in_(room_ids))
    ).all()
    counts: dict[int, int] = {}
    for room_id, user_id, show_online in rows:
        if is_shown_online(viewer_id, user_id, show_online):
            counts[room_id] = counts.get(room_id, 0) + 1
    return counts


# ---------- Listing and searching ----------
@router.get("")
def list_my_rooms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only the rooms the user belongs to. Other rooms are found via /search."""
    counts = member_counts(db)
    pending = dict(
        db.execute(select(JoinRequest.room_id, func.count()).group_by(JoinRequest.room_id)).all()
    )
    rooms = db.scalars(
        select(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == user.id)
        .where(Room.id.not_in(select(DirectChat.room_id)))
        .order_by(Room.name_lower)
    ).all()
    online = online_counts(db, [r.id for r in rooms], user.id)
    result = []
    for r in rooms:
        owner = r.owner_id == user.id
        result.append({
            "id": r.id,
            "name": r.name,
            "member_count": counts.get(r.id, 0),
            "online_count": online.get(r.id, 0),
            "is_member": True,
            "is_owner": owner,
            # Only owners see how many requests are waiting
            "pending_count": pending.get(r.id, 0) if owner else 0,
        })
    return result


@router.get("/search")
def search_rooms(
    q: str = Query(min_length=1, max_length=30),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = q.strip().lower()
    if not q:
        return []
    # autoescape=True makes "%" and "_" in the query match literally
    rooms = db.scalars(
        select(Room)
        .where(Room.name_lower.contains(q, autoescape=True))
        .where(Room.id.not_in(select(DirectChat.room_id)))
        .order_by(Room.name_lower)
        .limit(20)
    ).all()
    counts = member_counts(db)
    mine = set(db.scalars(select(RoomMember.room_id).where(RoomMember.user_id == user.id)))
    asked = set(db.scalars(select(JoinRequest.room_id).where(JoinRequest.user_id == user.id)))

    def status(room_id: int) -> str:
        if room_id in mine:
            return "member"
        return "pending" if room_id in asked else "none"

    return [
        {"id": r.id, "name": r.name, "member_count": counts.get(r.id, 0), "status": status(r.id)}
        for r in rooms
    ]


# ---------- Creating, leaving, deleting ----------
@router.post("", status_code=201)
def create_room(
    data: RoomCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    name = data.name.strip()
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="Room name must be at least 3 characters")
    if db.scalar(select(Room).where(Room.name_lower == name.lower())):
        raise HTTPException(status_code=409, detail="Room name is already taken")

    room = Room(name=name, name_lower=name.lower(), owner_id=user.id)
    db.add(room)
    try:
        db.flush()  # assigns room.id without committing yet
        db.add(RoomMember(user_id=user.id, room_id=room.id))  # creator joins automatically
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room name is already taken")
    return {"id": room.id, "name": room.name, "member_count": 1, "online_count": 1,
            "is_member": True, "is_owner": True, "pending_count": 0}


@router.delete("/{room_id}/leave")
def leave_room(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if is_direct(db, room_id):
        raise HTTPException(status_code=400, detail="Private chats can't be left")
    room = db.get(Room, room_id)
    if room and room.owner_id == user.id:
        raise HTTPException(status_code=400, detail="Owners can't leave. Delete the room instead")
    membership = db.get(RoomMember, (user.id, room_id))
    if membership:
        db.delete(membership)
        db.commit()
    return {"left": True}


# This one is async because it also has to close the room's open WebSockets
@router.delete("/{room_id}")
async def delete_room(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    room = get_owned_room(db, room_id, user)
    # Child rows first, then the room itself
    db.execute(delete(Message).where(Message.room_id == room_id))
    db.execute(delete(RoomMember).where(RoomMember.room_id == room_id))
    db.execute(delete(JoinRequest).where(JoinRequest.room_id == room_id))
    db.execute(delete(ReadState).where(ReadState.room_id == room_id))
    db.delete(room)
    db.commit()
    await manager.close_room(room_id)
    return {"deleted": True}


# ---------- Renaming ----------
@router.put("/{room_id}")
def rename_room(
    room_id: int,
    data: RoomCreate,  # same name rules as creating a room
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = get_owned_room(db, room_id, user)
    name = data.name.strip()
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="Room name must be at least 3 characters")

    # Exclude the room itself, so changing only the casing ("club" -> "Club") is allowed
    taken = db.scalar(
        select(Room).where(Room.name_lower == name.lower(), Room.id != room_id)
    )
    if taken:
        raise HTTPException(status_code=409, detail="Room name is already taken")

    room.name = name
    room.name_lower = name.lower()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Room name is already taken")
    return {"id": room.id, "name": room.name}


# ---------- About: description and members ----------
@router.get("/{room_id}/info")
def room_info(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Details of a room, only for its members."""
    if not is_member(db, user.id, room_id):
        raise HTTPException(status_code=403, detail="Join the room to see its details")
    if is_direct(db, room_id):
        raise HTTPException(status_code=400, detail="Private chats have no room details")
    room = db.get(Room, room_id)

    users = db.scalars(
        select(User).join(RoomMember, RoomMember.user_id == User.id).where(RoomMember.room_id == room_id)
    ).all()
    members = [
        {
            "id": u.id,
            "username": u.username,
            "avatar_color": u.avatar_color,
            "online": is_shown_online(user.id, u.id, u.show_online),
            "is_owner": u.id == room.owner_id,
        }
        for u in users
    ]
    # Owner first, then online people, then A-Z
    members.sort(key=lambda m: (not m["is_owner"], not m["online"], m["username"].lower()))
    return {
        "id": room.id,
        "name": room.name,
        "description": room.description,
        "is_owner": room.owner_id == user.id,
        "created_at": iso(room.created_at),
        "online_count": sum(1 for m in members if m["online"]),
        "members": members,
    }


@router.put("/{room_id}/description")
def set_description(
    room_id: int,
    data: DescriptionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = get_owned_room(db, room_id, user)
    room.description = data.description.strip()
    db.commit()
    return {"description": room.description}


# ---------- Join requests ----------
@router.post("/{room_id}/request")
def request_to_join(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if db.get(Room, room_id) is None or is_direct(db, room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    if is_member(db, user.id, room_id):
        return {"status": "member"}

    try:
        if db.get(JoinRequest, (user.id, room_id)) is None:
            db.add(JoinRequest(user_id=user.id, room_id=room_id))
            db.commit()
    except IntegrityError:
        db.rollback()  # double click, the row already exists, which is fine
    return {"status": "pending"}


@router.delete("/{room_id}/request")
def cancel_request(
    room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    pending = db.get(JoinRequest, (user.id, room_id))
    if pending:
        db.delete(pending)
        db.commit()
    return {"cancelled": True}


@router.get("/requests")
def incoming_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """All pending requests for rooms owned by the current user."""
    rows = db.execute(
        select(JoinRequest, Room, User)
        .join(Room, JoinRequest.room_id == Room.id)
        .join(User, JoinRequest.user_id == User.id)
        .where(Room.owner_id == user.id)
        .order_by(JoinRequest.created_at)
    ).all()
    return [
        {
            "room_id": room.id,
            "room_name": room.name,
            "user_id": requester.id,
            "username": requester.username,
            "avatar_color": requester.avatar_color,
            "created_at": iso(req.created_at),
        }
        for req, room, requester in rows
    ]


@router.post("/{room_id}/requests/{user_id}/approve")
def approve_request(
    room_id: int, user_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    get_owned_room(db, room_id, user)
    pending = db.get(JoinRequest, (user_id, room_id))
    if pending is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if not is_member(db, user_id, room_id):
        db.add(RoomMember(user_id=user_id, room_id=room_id))
    db.delete(pending)
    db.commit()
    return {"approved": True}


@router.post("/{room_id}/requests/{user_id}/deny")
def deny_request(
    room_id: int, user_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    get_owned_room(db, room_id, user)
    pending = db.get(JoinRequest, (user_id, room_id))
    if pending is None:
        raise HTTPException(status_code=404, detail="Request not found")
    db.delete(pending)
    db.commit()
    return {"denied": True}


# ---------- Messages ----------
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