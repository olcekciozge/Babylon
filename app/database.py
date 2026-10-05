from sqlalchemy import create_engine
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