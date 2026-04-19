def _preview(client, ac, msg="Con thấy áp lực."):
    r = client.post(
        "/messages/translate",
        json={"connection_id": ac["connection_id"], "raw_message": msg},
        headers=ac["founder_headers"],
    )
    return r.json()


def test_approve_happy(client, accepted_connection):
    p = _preview(client, accepted_connection)
    r = client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=accepted_connection["founder_headers"])
    assert r.status_code == 200
    assert r.json()["message_id"]


def test_approve_unknown(client, accepted_connection):
    r = client.post("/messages/approve", json={"preview_id": "nope"}, headers=accepted_connection["founder_headers"])
    assert r.status_code == 404


def test_approve_other_actor(client, accepted_connection):
    p = _preview(client, accepted_connection)
    r = client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=accepted_connection["receiver_headers"])
    assert r.status_code == 403


def test_approve_twice(client, accepted_connection):
    p = _preview(client, accepted_connection)
    client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=accepted_connection["founder_headers"])
    r = client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=accepted_connection["founder_headers"])
    assert r.status_code == 409


def test_approved_shows_in_list(client, accepted_connection):
    p = _preview(client, accepted_connection)
    client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=accepted_connection["founder_headers"])
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["receiver_headers"])
    assert len(r.json()["messages"]) >= 1


def test_approve_missing_body(client, accepted_connection):
    r = client.post("/messages/approve", json={}, headers=accepted_connection["founder_headers"])
    assert r.status_code == 422


def test_approve_no_auth(client):
    r = client.post("/messages/approve", json={"preview_id": "x"})
    assert r.status_code == 401


def test_approve_triggers_memory(client, accepted_connection):
    p = _preview(client, accepted_connection)
    client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=accepted_connection["founder_headers"])
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"])
    assert "memory" in r.json()
