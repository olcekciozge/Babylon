import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app import auth, dms, friends, models, rooms, unread, users  # noqa: F401  (models registers the tables)
from app.database import Base, SessionLocal, add_missing_columns, engine
from app.dms import are_friends
from app.manager import manager
from app.models import DirectChat, Message
from app.presence import presence
from app.rooms import is_member, iso

app = FastAPI()

Base.metadata.create_all(bind=engine)  # creates missing tables
add_missing_columns()  # adds new columns to tables that already exist
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(friends.router)
app.include_router(dms.router)
app.include_router(unread.router)


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/presence")
async def presence_socket(websocket: WebSocket, token: str = ""):
    with SessionLocal() as db:
        user = auth.get_user_from_token(token, db)
        info = {"id": user.id, "show_online": user.show_online} if user else None

    if info is None:
        await websocket.close(code=1008)
        return

    await presence.add(info["id"], websocket, info["show_online"])
    try:
        while True:
            await websocket.receive_text()  # we ignore the content, this just keeps the socket open
    except WebSocketDisconnect:
        await presence.remove(info["id"], websocket)


@app.websocket("/ws/{room_id}")
async def chat(websocket: WebSocket, room_id: int, token: str = ""):
    info = None
    # Check the token AND room membership before accepting the connection
    with SessionLocal() as db:
        user = auth.get_user_from_token(token, db)
        if user and is_member(db, user.id, room_id):
            # For a private chat, peer_id is the other person (None for normal rooms)
            direct = db.get(DirectChat, room_id)
            peer_id = None
            if direct:
                peer_id = direct.user_b_id if direct.user_a_id == user.id else direct.user_a_id
            # Private chats only work between people who are currently friends
            if peer_id is None or are_friends(db, user.id, peer_id):
                info = {
                    "id": user.id,
                    "username": user.username,
                    "color": user.avatar_color,
                    "peer_id": peer_id,
                }

    if info is None:
        await websocket.close(code=1008)
        return

    username = info["username"]
    is_dm = info["peer_id"] is not None
    await manager.connect(room_id, websocket, username)
    try:
        while True:
            # Clients send JSON: {"type": "message", "text": "..."} or {"type": "typing"}
            try:
                event = json.loads(await websocket.receive_text())
            except ValueError:
                continue  # not valid JSON, ignore it
            if not isinstance(event, dict):
                continue

            if event.get("type") == "typing":
                # Tell everyone except the person who is typing
                await manager.broadcast(
                    room_id, {"type": "typing", "username": username}, exclude=websocket
                )

            elif event.get("type") == "message":
                text = str(event.get("text", "")).strip()[:1000]
                if not text:
                    continue

                if is_dm:
                    # They may have been unfriended since the connection opened
                    with SessionLocal() as db:
                        still_friends = are_friends(db, info["id"], info["peer_id"])
                    if not still_friends:
                        manager.disconnect(room_id, websocket)
                        await websocket.close(code=4003)  # our own "no longer allowed" code
                        return

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
                # Members who are not looking at this chat get an unread badge
                await presence.notify_message(room_id, info["id"])
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)