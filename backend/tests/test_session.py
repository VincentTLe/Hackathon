def test_receiver_can_get_messages(client, accepted_connection):
    r = client.get(
        f"/messages/{accepted_connection['connection_id']}",
        headers=accepted_connection["receiver_headers"],
    )
    assert r.status_code == 200
    assert r.json()["viewer_role"] == "receiver"


def test_receiver_cannot_create_connection(client, accepted_connection):
    r = client.post(
        "/connections",
        json={"receiver_display_name": "x", "relationship": "y"},
        headers=accepted_connection["receiver_headers"],
    )
    assert r.status_code == 403


def test_old_session_invalid_after_rotation(client, connection):
    a = client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "A"}).json()
    client.post("/session/b-accept", json={"magic_link_token": connection["magic_link_token"], "receiver_name": "B"})
    r = client.get(
        f"/messages/{connection['connection_id']}",
        headers={"Authorization": f"Bearer {a['session_token']}"},
    )
    assert r.status_code == 401


def test_missing_token(client, connection):
    r = client.get(f"/messages/{connection['connection_id']}")
    assert r.status_code == 401


def test_malformed_bearer(client, connection):
    r = client.get(
        f"/messages/{connection['connection_id']}",
        headers={"Authorization": "Bearer "},
    )
    assert r.status_code == 401


def test_founder_viewer_role(client, founder, accepted_connection):
    r = client.get(
        f"/messages/{accepted_connection['connection_id']}",
        headers=founder["headers"],
    )
    assert r.json()["viewer_role"] == "founder"
