from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # What the user sees, e.g. "Alice"
    username: Mapped[str] = mapped_column(String(20))
    # Lowercase copy used for the uniqueness check, so "Alice" and "alice" collide
    username_lower: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    bio: Mapped[str] = mapped_column(String(160), default="")
    avatar_color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    # Used in a later step: when False, the user always appears offline
    show_online: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    name_lower: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    # Every room has an owner, who approves join requests and can delete the room
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RoomMember(Base):
    """Join table: which user belongs to which room."""

    __tablename__ = "room_members"

    # A composite primary key also guarantees a user can't join the same room twice
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), primary_key=True)


class JoinRequest(Base):
    """A pending request to join a room. Approved or denied requests are deleted."""

    __tablename__ = "join_requests"

    # Composite key: one pending request per user per room
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()

class Friendship(Base):
    """One row per relationship. 'pending' means requester asked, addressee hasn't answered."""

    __tablename__ = "friendships"

    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    addressee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)