def test_friend_request_and_accept(client, alice, bob):
    assert client.post("/api/friends/request", json={"username": "bob"}, headers=alice.headers).status_code == 200
    bob_view = client.get("/api/friends", headers=bob.headers).json()
    assert [p["username"] for p in bob_view["incoming"]] == ["alice"]
    assert [p["username"] for p in client.get("/api/friends", headers=alice.headers).json()["outgoing"]] == ["bob"]
    assert client.post(f"/api/friends/{alice.id}/accept", headers=bob.headers).status_code == 200
    assert [p["username"] for p in client.get("/api/friends", headers=alice.headers).json()["friends"]] == ["bob"]


def test_cannot_add_yourself_or_unknown_users(client, alice):
    assert client.post("/api/friends/request", json={"username": "alice"}, headers=alice.headers).status_code == 400
    assert client.post("/api/friends/request", json={"username": "ghost"}, headers=alice.headers).status_code == 404


def test_duplicate_requests_are_rejected(client, alice, bob):
    client.post("/api/friends/request", json={"username": "bob"}, headers=alice.headers)
    assert client.post("/api/friends/request", json={"username": "bob"}, headers=alice.headers).status_code == 409
    client.post(f"/api/friends/{alice.id}/accept", headers=bob.headers)
    assert client.post("/api/friends/request", json={"username": "bob"}, headers=alice.headers).status_code == 409


def test_mutual_requests_become_friends(client, alice, bob):
    client.post("/api/friends/request", json={"username": "bob"}, headers=alice.headers)
    client.post("/api/friends/request", json={"username": "alice"}, headers=bob.headers)
    assert len(client.get("/api/friends", headers=alice.headers).json()["friends"]) == 1


def test_only_the_addressee_can_accept(client, alice, bob):
    client.post("/api/friends/request", json={"username": "bob"}, headers=alice.headers)
    assert client.post(f"/api/friends/{bob.id}/accept", headers=alice.headers).status_code == 404


def test_remove_friend(client, alice, bob, befriend):
    befriend(alice, bob)
    assert client.delete(f"/api/friends/{bob.id}", headers=alice.headers).status_code == 200
    assert client.get("/api/friends", headers=bob.headers).json()["friends"] == []


def test_dm_requires_friendship(client, alice, bob, befriend):
    assert client.post(f"/api/dms/{bob.id}", headers=alice.headers).status_code == 403
    befriend(alice, bob)
    r = client.post(f"/api/dms/{bob.id}", headers=alice.headers)
    assert r.status_code == 200
    again = client.post(f"/api/dms/{alice.id}", headers=bob.headers)
    assert again.json()["room_id"] == r.json()["room_id"]  # same chat from both sides


def test_cannot_dm_yourself(client, alice):
    assert client.post(f"/api/dms/{alice.id}", headers=alice.headers).status_code == 400


def test_dms_are_hidden_from_rooms_and_search(client, alice, bob, befriend):
    befriend(alice, bob)
    client.post(f"/api/dms/{bob.id}", headers=alice.headers)
    assert client.get("/api/rooms", headers=alice.headers).json() == []
    assert client.get("/api/rooms/search?q=dm", headers=bob.headers).json() == []
    assert len(client.get("/api/dms", headers=alice.headers).json()) == 1


def test_dm_is_private_to_its_two_people(client, alice, bob, carol, befriend):
    befriend(alice, bob)
    room_id = client.post(f"/api/dms/{bob.id}", headers=alice.headers).json()["room_id"]
    assert client.get(f"/api/rooms/{room_id}/messages", headers=carol.headers).status_code == 403
    assert client.post(f"/api/rooms/{room_id}/request", headers=carol.headers).status_code in (400, 404)
    assert client.delete(f"/api/rooms/{room_id}", headers=alice.headers).status_code == 400