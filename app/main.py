import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import select

from app import auth, models, rooms, users  # noqa: F401  (models registers the tables)
from app.database import Base, SessionLocal, engine
from app.models import Message, Room, RoomMember, User
from app.rooms import iso, is_member

app = FastAPI()

Base.metadata.create_all(bind=engine)  # creates missing tables
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)


def seed_default_room():
    """Creates the 'General' room on first run and adds all existing users to it."""
    with SessionLocal() as db:
        if db.scalar(select(Room).where(Room.name_lower == "general")):
            return
        general = Room(name="General", name_lower="general")
        db.add(general)
        db.flush()
        for user_id in db.scalars(select(User.id)):
            db.add(RoomMember(user_id=user_id, room_id=general.id))
        db.commit()


seed_default_room()


class ConnectionManager:
    def __init__(self):
        # room_id -> {connection: username}
        self.rooms: dict[int, dict[WebSocket, str]] = {}

    async def connect(self, room_id: int, websocket: WebSocket, username: str):
        await websocket.accept()
        self.rooms.setdefault(room_id, {})[websocket] = username

    def disconnect(self, room_id: int, websocket: WebSocket):
        room = self.rooms.get(room_id)
        if room is None:
            return
        room.pop(websocket, None)
        if not room:
            del self.rooms[room_id]  # nobody left, free the memory

    async def broadcast(self, room_id: int, payload: dict):
        data = json.dumps(payload)
        # Only the connections in THIS room receive the message
        for connection in list(self.rooms.get(room_id, {})):
            try:
                await connection.send_text(data)
            except Exception:
                self.disconnect(room_id, connection)  # dead connection, drop it


manager = ConnectionManager()


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws/{room_id}")
async def chat(websocket: WebSocket, room_id: int, token: str = ""):
    # Check the token AND room membership before accepting the connection
    with SessionLocal() as db:
        user = auth.get_user_from_token(token, db)
        if user and is_member(db, user.id, room_id):
            info = {"id": user.id, "username": user.username, "color": user.avatar_color}
        else:
            info = None

    if info is None:
        await websocket.close(code=1008)
        return

    username = info["username"]
    await manager.connect(room_id, websocket, username)
    await manager.broadcast(room_id, {"type": "system", "text": f"{username} joined the chat"})
    try:
        while True:
            text = (await websocket.receive_text()).strip()[:1000]
            if not text:
                continue
            # Save first, then broadcast, so what users see is what's stored
            with SessionLocal() as db:
                message = Message(room_id=room_id, user_id=info["id"], text=text)
                db.add(message)
                db.commit()
                created_at = iso(message.created_at)
            await manager.broadcast(room_id, {
                "type": "message",
                "username": username,
                "avatar_color": info["color"],
                "text": text,
                "created_at": created_at,
            })
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
        await manager.broadcast(room_id, {"type": "system", "text": f"{username} left the chat"})