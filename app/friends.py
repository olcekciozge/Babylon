from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Friendship, User

router = APIRouter(prefix="/api/friends", tags=["friends"])


class FriendRequest(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,20}$")


def find_relation(db: Session, a: int, b: int) -> Friendship | None:
    """Finds the relationship between two users, whoever sent the request."""
    return db.scalar(
        select(Friendship).where(
            or_(
                and_(Friendship.requester_id == a, Friendship.addressee_id == b),
                and_(Friendship.requester_id == b, Friendship.addressee_id == a),
            )
        )
    )


def person(u: User) -> dict:
    return {"id": u.id, "username": u.username, "avatar_color": u.avatar_color}


@router.get("")
def list_friends(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rels = db.scalars(
        select(Friendship).where(
            or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id)
        )
    ).all()

    def other_id(r: Friendship) -> int:
        return r.addressee_id if r.requester_id == user.id else r.requester_id

    ids = {other_id(r) for r in rels}
    people = {}
    if ids:
        people = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}

    friends, incoming, outgoing = [], [], []
    for r in rels:
        other = people.get(other_id(r))
        if other is None:
            continue
        if r.status == "accepted":
            friends.append(person(other))
        elif r.requester_id == user.id:
            outgoing.append(person(other))
        else:
            incoming.append(person(other))

    friends.sort(key=lambda p: p["username"].lower())
    return {"friends": friends, "incoming": incoming, "outgoing": outgoing}


@router.post("/request")
def send_request(
    data: FriendRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    target = db.scalar(select(User).where(User.username_lower == data.username.lower()))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="You can't add yourself")

    relation = find_relation(db, user.id, target.id)
    if relation:
        if relation.status == "accepted":
            raise HTTPException(status_code=409, detail="You are already friends")
        if relation.requester_id == user.id:
            raise HTTPException(status_code=409, detail="Request already sent")
        # They already asked us, so asking back means we accept
        relation.status = "accepted"
        db.commit()
        return {"status": "accepted"}

    db.add(Friendship(requester_id=user.id, addressee_id=target.id, status="pending"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Request already sent")
    return {"status": "pending"}


@router.post("/{user_id}/accept")
def accept_request(
    user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # Only requests sent TO me can be accepted by me
    relation = db.scalar(
        select(Friendship).where(
            Friendship.requester_id == user_id,
            Friendship.addressee_id == user.id,
            Friendship.status == "pending",
        )
    )
    if relation is None:
        raise HTTPException(status_code=404, detail="Request not found")
    relation.status = "accepted"
    db.commit()
    return {"status": "accepted"}


@router.delete("/{user_id}")
def remove_relation(
    user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Declines a request, cancels one I sent, or removes a friend."""
    relation = find_relation(db, user.id, user_id)
    if relation:
        db.delete(relation)
        db.commit()
    return {"removed": True}