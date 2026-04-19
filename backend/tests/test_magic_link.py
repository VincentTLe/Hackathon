def test_invite_preview_ok(client, founder, connection):
    r = client.get(f"/connections/invite/{connection['magic_link_token']}")
    assert r.status_code == 200
    d = r.json()
    assert d["founder_name"] == founder["name"]
    assert d["relationship"] == "mother"


def test_invite_preview_garbage(client):
    r = client.get("/connections/invite/garbage-token-nope")
    assert r.status_code == 404


def test_accept_happy(client, connection):
    r = client.post(
        "/session/b-accept",
        json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["session_token"]
    assert d["connection_id"] == connection["connection_id"]


def test_accept_rotates_token(client, connection):
    a = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M1"}).json()
    b = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M2"}).json()
    assert a["session_token"] != b["session_token"]


def test_accept_marks_connection(client, founder, connection):
    client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M"})
    r = client.get("/connections", headers=founder["headers"])
    item = next(c for c in r.json()["connections"] if c["id"] == connection["connection_id"])
    assert item["accepted"] is True


def test_accept_empty_name(client, connection):
    r = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": ""})
    assert r.status_code == 422


def test_accept_unknown_token(client):
    r = client.post("/session/b-accept", json={"magic_link_token": "nope", "receiver_name": "M"})
    assert r.status_code == 404


def test_accept_returns_founder_name(client, founder, connection):
    r = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M"}).json()
    assert r["founder_name"] == founder["name"]


def test_session_token_differs_from_founder(client, founder, connection):
    r = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M"}).json()
    assert r["session_token"] != founder["founder_token"]


def test_session_token_length(client, connection):
    r = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "M"}).json()
    assert len(r["session_token"]) >= 32
