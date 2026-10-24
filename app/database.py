from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///./babylon.db"

# check_same_thread=False is required for SQLite when used with FastAPI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Gives each request its own database session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns():
    """A tiny stand-in for a migration tool.

    create_all() creates missing tables but never adds columns to tables that already exist,
    so new columns are added here. Real projects use a tool like Alembic for this.
    """
    with engine.begin() as conn:
        room_columns = {c["name"] for c in inspect(conn).get_columns("rooms")}
        if "description" not in room_columns:
            conn.execute(text("ALTER TABLE rooms ADD COLUMN description VARCHAR(200) NOT NULL DEFAULT ''"))