from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # What the user sees, e.g. "Alice"
    username: Mapped[str] = mapped_column(String(20))
    # Lowercase copy used for the uniqueness check, so "Alice" and "alice" collide
    username_lower: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Profile fields (used in step 7, added now to avoid a migration later)
    bio: Mapped[str] = mapped_column(String(160), default="")
    avatar_color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )