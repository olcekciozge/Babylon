from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Message, ReadState, RoomMember, User

router = APIRouter(prefix="/api", tags=["unread"])


@router.get("/unread")
def unread_counts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """How many messages from other people each of my chats has since I last read it."""
    room_ids = list(db.scalars(select(RoomMember.room_id).where(RoomMember.user_id == user.id)))
    if not room_ids:
        return {"counts": {}}

    # A chat I've never opened has no marker yet: start it at the newest message,
    # so old history doesn't show up as "unread"
    have_marker = set(db.scalars(select(ReadState.room_id).where(ReadState.user_id == user.id)))
    missing = [r for r in room_ids if r not in have_marker]
    if missing:
        latest = dict(
            db.execute(
                select(Message.room_id, func.max(Message.id))
                .where(Message.room_id.in_(missing))
                .group_by(Message.room_id)
            ).all()
        )
        for room_id in missing:
            db.add(ReadState(user_id=user.id, room_id=room_id, last_read_id=latest.get(room_id, 0)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # two requests created the same marker at once, which is fine

    rows = db.execute(
        select(Message.room_id, func.count())
        .join(ReadState, and_(ReadState.room_id == Message.room_id, ReadState.user_id == user.id))
        .where(
            Message.room_id.in_(room_ids),
            Message.user_id != user.id,  # my own messages are never unread
            Message.id > ReadState.last_read_id,
        )
        .group_by(Message.room_id)
    ).all()
    return {"counts": {room_id: count for room_id, count in rows}}


@router.post("/rooms/{room_id}/read")
def mark_read(room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.get(RoomMember, (user.id, room_id)) is None:
        raise HTTPException(status_code=403, detail="Join the room first")

    latest = db.scalar(select(func.max(Message.id)).where(Message.room_id == room_id)) or 0
    state = db.get(ReadState, (user.id, room_id))
    if state is None:
        db.add(ReadState(user_id=user.id, room_id=room_id, last_read_id=latest))
    elif latest > state.last_read_id:
        state.last_read_id = latest  # the marker only ever moves forward
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"read": True}