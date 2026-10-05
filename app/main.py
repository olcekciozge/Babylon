import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app import auth, models, users  # noqa: F401  (models registers the tables)
from app.database import Base, SessionLocal, engine

app = FastAPI()

Base.metadata.create_all(bind=engine)  # creates tables if they don't exist
app.include_router(auth.router)
app.include_router(users.router)

class ConnectionManager:
    def __init__(self):
        # Maps each connection to its username
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections[websocket] = username

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)

    async def broadcast(self, payload: dict):
        data = json.dumps(payload)
        for connection in list(self.active_connections):
            await connection.send_text(data)


manager = ConnectionManager()


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def chat(websocket: WebSocket, token: str = ""):
    with SessionLocal() as db:
        user = auth.get_user_from_token(token, db)
        profile = (
            {"username": user.username, "avatar_color": user.avatar_color}
            if user
            else None
        )

    if profile is None:
        await websocket.close(code=1008)
        return

    username = profile["username"]
    color = profile["avatar_color"]

    await manager.connect(websocket, username)
    await manager.broadcast({"type": "system", "text": f"{username} joined the chat"})
    try:
        while True:
            text = await websocket.receive_text()
            await manager.broadcast({
                "type": "message",
                "username": username,
                "avatar_color": color,
                "text": text,
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast({"type": "system", "text": f"{username} left the chat"})