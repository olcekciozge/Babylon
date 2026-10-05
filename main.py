import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI()


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
        # list() makes a copy, so the dict can change safely while we loop
        for connection in list(self.active_connections):
            await connection.send_text(data)


manager = ConnectionManager()


@app.get("/")
async def index():
    return FileResponse("index.html")


@app.websocket("/ws")
async def chat(websocket: WebSocket, username: str = "Anonymous"):
    # Clean the username: trim spaces, limit length, fall back to a default
    username = username.strip()[:20] or "Anonymous"

    await manager.connect(websocket, username)
    await manager.broadcast({"type": "system", "text": f"{username} joined the chat"})
    try:
        while True:
            text = await websocket.receive_text()
            await manager.broadcast({"type": "message", "username": username, "text": text})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast({"type": "system", "text": f"{username} left the chat"})