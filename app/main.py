from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app import auth, models, rooms, users  # noqa: F401  (models registers the tables)
from app.database import Base, SessionLocal, engine
from app.manager import manager
from app.models import Message
from app.rooms import is_member, iso

app = FastAPI()

Base.metadata.create_all(bind=engine)  # creates missing tables
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)


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