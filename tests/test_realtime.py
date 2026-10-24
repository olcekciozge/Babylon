import pytest
from starlette.websockets import WebSocketDisconnect


def open_dm(client, a, b):
    return client.post(f"/api/dms/{b.id}", headers=a.headers).json()["room_id"]


def test_messages_are_broadcast_and_saved(client, alice, bob, make_room, join_room, chat_ws):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    with chat_ws(room["id"], alice) as a, chat_ws(room["id"], bob) as b:
        a.send_json({"type": "message", "text": "hello bob"})
        for ws in (a, b):
            event = ws.receive_json()
            assert event["type"] == "message" and event["text"] == "hello bob" and event["username"] == "alice"
    history = client.get(f"/api/rooms/{room['id']}/messages", headers=bob.headers).json()
    assert [m["text"] for m in history] == ["hello bob"]


def test_blank_messages_are_ignored_and_long_ones_are_cut(client, alice, make_room, chat_ws):
    room = make_room(alice, "Study Group")
    with chat_ws(room["id"], alice) as ws:
        ws.send_json({"type": "message", "text": "   "})
        ws.send_json({"type": "message", "text": "x" * 5000})
        assert len(ws.receive_json()["text"]) == 1000  # the blank one produced no event
    texts = [m["text"] for m in client.get(f"/api/rooms/{room['id']}/messages", headers=alice.headers).json()]
    assert [len(t) for t in texts] == [1000]


def test_typing_goes_to_others_only(alice, bob, make_room, join_room, chat_ws):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    with chat_ws(room["id"], alice) as a, chat_ws(room["id"], bob) as b:
        a.send_json({"type": "typing"})
        assert b.receive_json() == {"type": "typing", "username": "alice"}
        # alice does not get her own typing event: her next event is her message
        a.send_json({"type": "message", "text": "hi"})
        assert a.receive_json()["type"] == "message"


def test_websocket_rejects_bad_token_and_non_members(client, alice, bob, make_room, chat_ws):
    room = make_room(alice, "Study Group")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/{room['id']}?token=garbage"):
            pass
    assert exc.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as exc:
        with chat_ws(room["id"], bob):
            pass
    assert exc.value.code == 1008


def test_deleting_a_room_closes_open_sockets(client, alice, make_room, chat_ws):
    room = make_room(alice, "Study Group")
    with chat_ws(room["id"], alice) as ws:
        client.delete(f"/api/rooms/{room['id']}", headers=alice.headers)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4004


def test_dm_websocket_needs_friendship(client, alice, bob, befriend, chat_ws):
    befriend(alice, bob)
    room_id = open_dm(client, alice, bob)
    with chat_ws(room_id, alice) as a, chat_ws(room_id, bob) as b:
        a.send_json({"type": "message", "text": "psst"})
        assert b.receive_json()["text"] == "psst"
        a.receive_json()
    client.delete(f"/api/friends/{bob.id}", headers=alice.headers)
    with pytest.raises(WebSocketDisconnect):
        with chat_ws(room_id, bob):
            pass


def test_unfriending_closes_an_open_dm(client, alice, bob, befriend, chat_ws):
    befriend(alice, bob)
    room_id = open_dm(client, alice, bob)
    with chat_ws(room_id, alice) as a:
        client.delete(f"/api/friends/{alice.id}", headers=bob.headers)
        a.send_json({"type": "message", "text": "still there?"})
        with pytest.raises(WebSocketDisconnect) as exc:
            a.receive_json()
        assert exc.value.code == 4003


def test_unread_counts_and_read_marker(client, alice, bob, make_room, join_room, chat_ws):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    assert client.get("/api/unread", headers=bob.headers).json()["counts"] == {}  # creates the marker
    with chat_ws(room["id"], alice) as a:
        a.send_json({"type": "message", "text": "one"})
        a.receive_json()
        a.send_json({"type": "message", "text": "two"})
        a.receive_json()
    assert client.get("/api/unread", headers=bob.headers).json()["counts"] == {str(room["id"]): 2}
    assert client.get("/api/unread", headers=alice.headers).json()["counts"] == {}  # own messages never count
    assert client.post(f"/api/rooms/{room['id']}/read", headers=bob.headers).status_code == 200
    assert client.get("/api/unread", headers=bob.headers).json()["counts"] == {}


def test_old_history_is_not_unread_for_new_members(client, alice, bob, make_room, join_room, chat_ws):
    room = make_room(alice, "Study Group")
    with chat_ws(room["id"], alice) as a:
        a.send_json({"type": "message", "text": "before bob"})
        a.receive_json()
    join_room(room, alice, bob)
    assert client.get("/api/unread", headers=bob.headers).json()["counts"] == {}


def test_presence_online_flag(client, alice, bob, befriend, presence_ws):
    befriend(alice, bob)

    def bob_online():
        return client.get("/api/friends", headers=alice.headers).json()["friends"][0]["online"]

    assert bob_online() is False
    with presence_ws(bob):
        assert bob_online() is True
        # Hiding online status makes bob look offline to friends
        client.put("/api/users/me/visibility", json={"show_online": False}, headers=bob.headers)
        assert bob_online() is False
        client.put("/api/users/me/visibility", json={"show_online": True}, headers=bob.headers)
        assert bob_online() is True
    assert bob_online() is False


def test_presence_pushes_unread_events(client, alice, bob, befriend, presence_ws, chat_ws):
    befriend(alice, bob)
    room_id = open_dm(client, alice, bob)
    with presence_ws(bob) as p, chat_ws(room_id, alice) as a:
        a.send_json({"type": "message", "text": "ping"})
        a.receive_json()
        events = []
        for _ in range(5):
            event = p.receive_json()
            events.append(event)
            if event.get("type") == "unread":
                break
        assert {"type": "unread", "room_id": room_id} in events