import os
import tempfile
from dataclasses import dataclass

# The database location has to be set BEFORE the app is imported,
# because app/database.py reads it when it is first imported.
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.manager import manager  # noqa: E402
from app.presence import presence  # noqa: E402


@dataclass
class Account:
    id: int
    username: str
    token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts with empty tables and no open connections."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    manager.rooms.clear()
    presence.connections.clear()
    yield


@pytest.fixture
def client():
    # Using the client as a context manager keeps one event loop alive,
    # so several WebSocket connections in one test can talk to each other.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signup(client):
    """Creates an account and logs in. Returns an Account with a valid token."""

    def _signup(username: str, password: str = "password123") -> Account:
        response = client.post("/api/auth/register", json={"username": username, "password": password})
        assert response.status_code == 201, response.text
        user_id = response.json()["id"]
        response = client.post("/api/auth/login", data={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return Account(id=user_id, username=username, token=response.json()["access_token"])

    return _signup


@pytest.fixture
def alice(signup):
    return signup("alice")


@pytest.fixture
def bob(signup):
    return signup("bob")


@pytest.fixture
def carol(signup):
    return signup("carol")


@pytest.fixture
def befriend(client):
    """Makes two accounts friends (request + accept)."""

    def _befriend(a: Account, b: Account):
        assert client.post("/api/friends/request", json={"username": b.username}, headers=a.headers).status_code == 200
        assert client.post(f"/api/friends/{a.id}/accept", headers=b.headers).status_code == 200

    return _befriend


@pytest.fixture
def make_room(client):
    def _make_room(owner: Account, name: str) -> dict:
        response = client.post("/api/rooms", json={"name": name}, headers=owner.headers)
        assert response.status_code == 201, response.text
        return response.json()

    return _make_room


@pytest.fixture
def join_room(client):
    """A member asks to join and the owner accepts."""

    def _join_room(room: dict, owner: Account, member: Account):
        assert client.post(f"/api/rooms/{room['id']}/request", headers=member.headers).status_code == 200
        response = client.post(f"/api/rooms/{room['id']}/requests/{member.id}/approve", headers=owner.headers)
        assert response.status_code == 200, response.text

    return _join_room


@pytest.fixture
def chat_ws(client):
    """Opens the chat WebSocket of a room as a given account (use it in a `with` block)."""

    def _chat_ws(room_id: int, account: Account):
        return client.websocket_connect(f"/ws/{room_id}?token={account.token}")

    return _chat_ws


@pytest.fixture
def presence_ws(client):
    def _presence_ws(account: Account):
        return client.websocket_connect(f"/presence?token={account.token}")

    return _presence_ws