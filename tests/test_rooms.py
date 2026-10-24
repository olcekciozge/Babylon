def test_create_room_and_unique_names(client, alice, bob, make_room):
    room = make_room(alice, "Study Group")
    assert room["name"] == "Study Group"
    r = client.post("/api/rooms", json={"name": "study group"}, headers=bob.headers)
    assert r.status_code == 409


def test_invalid_room_names(client, alice):
    for name in ["ab", "#general", "x" * 31, "   "]:
        r = client.post("/api/rooms", json={"name": name}, headers=alice.headers)
        assert r.status_code == 422, name


def test_my_rooms_lists_member_and_online_counts(client, alice, bob, make_room, join_room):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    rooms = client.get("/api/rooms", headers=alice.headers).json()
    assert rooms[0]["member_count"] == 2
    assert rooms[0]["is_owner"] is True
    assert client.get("/api/rooms", headers=bob.headers).json()[0]["is_owner"] is False


def test_search_finds_rooms_by_name(client, alice, bob, make_room):
    make_room(alice, "Python Lovers")
    make_room(alice, "Cooking")
    names = [r["name"] for r in client.get("/api/rooms/search?q=pyth", headers=bob.headers).json()]
    assert names == ["Python Lovers"]


def test_search_treats_wildcards_literally(client, alice, bob, make_room):
    make_room(alice, "Python Lovers")
    assert client.get("/api/rooms/search?q=%25", headers=bob.headers).json() == []


def test_join_request_flow(client, alice, bob, make_room):
    room = make_room(alice, "Study Group")
    # Not a member yet: can't read messages
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=bob.headers).status_code == 403
    assert client.post(f"/api/rooms/{room['id']}/request", headers=bob.headers).status_code == 200
    pending = client.get("/api/rooms/requests", headers=alice.headers).json()
    assert len(pending) == 1 and pending[0]["username"] == "bob"
    # A request alone doesn't grant access
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=bob.headers).status_code == 403
    # Only the owner can approve
    assert client.post(f"/api/rooms/{room['id']}/requests/{bob.id}/approve", headers=bob.headers).status_code == 403
    assert client.post(f"/api/rooms/{room['id']}/requests/{bob.id}/approve", headers=alice.headers).status_code == 200
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=bob.headers).status_code == 200


def test_deny_request(client, alice, bob, make_room):
    room = make_room(alice, "Study Group")
    client.post(f"/api/rooms/{room['id']}/request", headers=bob.headers)
    assert client.post(f"/api/rooms/{room['id']}/requests/{bob.id}/deny", headers=alice.headers).status_code == 200
    assert client.get("/api/rooms/requests", headers=alice.headers).json() == []
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=bob.headers).status_code == 403


def test_only_owner_can_rename_describe_and_delete(client, alice, bob, make_room, join_room):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    rid = room["id"]
    assert client.put(f"/api/rooms/{rid}", json={"name": "Hacked"}, headers=bob.headers).status_code == 403
    assert client.put(f"/api/rooms/{rid}/description", json={"description": "x"}, headers=bob.headers).status_code == 403
    assert client.delete(f"/api/rooms/{rid}", headers=bob.headers).status_code == 403
    assert client.put(f"/api/rooms/{rid}", json={"name": "Renamed"}, headers=alice.headers).status_code == 200


def test_description_and_member_info(client, alice, bob, make_room, join_room):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    rid = room["id"]
    r = client.put(f"/api/rooms/{rid}/description", json={"description": "We study."}, headers=alice.headers)
    assert r.status_code == 200
    info = client.get(f"/api/rooms/{rid}/info", headers=bob.headers).json()
    assert info["description"] == "We study."
    owners = [m["username"] for m in info["members"] if m["is_owner"]]
    assert owners == ["alice"] and len(info["members"]) == 2
    too_long = client.put(f"/api/rooms/{rid}/description", json={"description": "x" * 201}, headers=alice.headers)
    assert too_long.status_code == 422


def test_info_requires_membership(client, alice, bob, make_room):
    room = make_room(alice, "Study Group")
    assert client.get(f"/api/rooms/{room['id']}/info", headers=bob.headers).status_code == 403


def test_leave_and_owner_cannot_leave(client, alice, bob, make_room, join_room):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    assert client.delete(f"/api/rooms/{room['id']}/leave", headers=alice.headers).status_code == 400
    assert client.delete(f"/api/rooms/{room['id']}/leave", headers=bob.headers).status_code == 200
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=bob.headers).status_code == 403


def test_delete_room_removes_it(client, alice, bob, make_room, join_room):
    room = make_room(alice, "Study Group")
    join_room(room, alice, bob)
    assert client.delete(f"/api/rooms/{room['id']}", headers=alice.headers).status_code == 200
    assert client.get("/api/rooms", headers=bob.headers).json() == []
    assert client.get("/api/rooms/search?q=Study", headers=bob.headers).json() == []