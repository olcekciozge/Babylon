def test_register_and_login(client):
    r = client.post("/api/auth/register", json={"username": "alice", "password": "password123"})
    assert r.status_code == 201
    r = client.post("/api/auth/login", data={"username": "alice", "password": "password123"})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"


def test_usernames_are_unique_ignoring_case(client, alice):
    r = client.post("/api/auth/register", json={"username": "ALICE", "password": "password123"})
    assert r.status_code == 409


def test_wrong_password_is_rejected(client, alice):
    r = client.post("/api/auth/login", data={"username": "alice", "password": "nope-nope"})
    assert r.status_code == 401


def test_login_is_case_insensitive(client, alice):
    r = client.post("/api/auth/login", data={"username": "ALICE", "password": "password123"})
    assert r.status_code == 200


def test_invalid_registration_is_rejected(client):
    assert client.post("/api/auth/register", json={"username": "a", "password": "password123"}).status_code == 422
    assert client.post("/api/auth/register", json={"username": "alice", "password": "short"}).status_code == 422


def test_me_requires_a_valid_token(client, alice):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/api/auth/me", headers=alice.headers).json()["username"] == "alice"


def test_update_profile(client, alice):
    r = client.put("/api/users/me", json={"bio": "Hello there", "avatar_color": "#fbbf24"}, headers=alice.headers)
    assert r.status_code == 200
    me = client.get("/api/users/me", headers=alice.headers).json()
    assert me["bio"] == "Hello there" and me["avatar_color"] == "#fbbf24"


def test_public_profile_hides_private_fields(client, alice, bob):
    data = client.get("/api/users/alice", headers=bob.headers).json()
    assert data["username"] == "alice"
    assert "show_online" not in data
    assert client.get("/api/users/nobody", headers=bob.headers).status_code == 404


def test_change_username_needs_the_password(client, alice, bob):
    url = "/api/users/me/username"
    r = client.put(url, json={"new_username": "alice2", "password": "wrong-password"}, headers=alice.headers)
    assert r.status_code == 401
    r = client.put(url, json={"new_username": "alice2", "password": "password123"}, headers=alice.headers)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=alice.headers).json()["username"] == "alice2"
    # Taking someone else's name fails, even with different capitalization
    r = client.put(url, json={"new_username": "BOB", "password": "password123"}, headers=alice.headers)
    assert r.status_code == 409