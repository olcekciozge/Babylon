import json

from fastapi import WebSocket


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

    async def close_room(self, room_id: int):
        """Disconnects everyone in a room (used when the room is deleted)."""
        for connection in list(self.rooms.get(room_id, {})):
            try:
                await connection.close(code=4004)  # 4004 = our own "room deleted" code
            except Exception:
                pass
        self.rooms.pop(room_id, None)


manager = ConnectionManager()