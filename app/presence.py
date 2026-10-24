import json

from fastapi import WebSocket
from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models import Friendship, RoomMember, User


class PresenceManager:
    def __init__(self):
        # user_id -> that user's open connections (one per browser tab)
        self.connections: dict[int, set[WebSocket]] = {}

    def is_online(self, user_id: int) -> bool:
        return bool(self.connections.get(user_id))

    def visible_online(self, user_id: int, show_online: bool) -> bool:
        """What OTHER people see: online only if connected AND the user allows it."""
        return show_online and self.is_online(user_id)

    async def add(self, user_id: int, websocket: WebSocket, show_online: bool):
        await websocket.accept()
        first_tab = not self.is_online(user_id)
        self.connections.setdefault(user_id, set()).add(websocket)
        if first_tab and show_online:
            await self.notify_friends(user_id, True)

    async def remove(self, user_id: int, websocket: WebSocket):
        tabs = self.connections.get(user_id)
        if tabs is None:
            return
        tabs.discard(websocket)
        if not tabs:
            del self.connections[user_id]
            # Read the setting fresh, the user may have changed it while connected
            with SessionLocal() as db:
                user = db.get(User, user_id)
                show = bool(user and user.show_online)
            if show:
                await self.notify_friends(user_id, False)

    async def notify_friends(self, user_id: int, online: bool):
        """Sends 'user X is now online/offline' to every online friend of X."""
        with SessionLocal() as db:
            rels = db.scalars(
                select(Friendship).where(
                    Friendship.status == "accepted",
                    or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
                )
            ).all()
            friend_ids = [
                r.addressee_id if r.requester_id == user_id else r.requester_id for r in rels
            ]

        data = json.dumps({"type": "presence", "user_id": user_id, "online": online})
        for friend_id in friend_ids:
            for connection in list(self.connections.get(friend_id, ())):
                try:
                    await connection.send_text(data)
                except Exception:
                    pass  # dead connection, its own handler will clean it up

    async def notify_message(self, room_id: int, sender_id: int):
        """Tells every other member of a room that a new message arrived (drives the unread badges)."""
        with SessionLocal() as db:
            member_ids = list(
                db.scalars(
                    select(RoomMember.user_id).where(
                        RoomMember.room_id == room_id, RoomMember.user_id != sender_id
                    )
                )
            )

        data = json.dumps({"type": "unread", "room_id": room_id})
        for member_id in member_ids:
            for connection in list(self.connections.get(member_id, ())):
                try:
                    await connection.send_text(data)
                except Exception:
                    pass


presence = PresenceManager()