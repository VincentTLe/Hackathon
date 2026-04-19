def _send_approve(client, ac, headers, msg):
    p = client.post("/messages/translate", json={"connection_id": ac["connection_id"], "raw_message": msg}, headers=headers).json()
    client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=headers)


def test_memory_empty_initial(client, accepted_connection):
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    assert r["memory"]["summary"] == ""


def test_memory_after_one_message(client, accepted_connection):
    _send_approve(client, accepted_connection, accepted_connection["founder_headers"], "I feel distant from you lately.")
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    assert r["memory"]["summary"]


def test_memory_themes_after_roundtrips(client, accepted_connection):
    for msg in ["hi mom", "i miss you", "thanks for listening"]:
        _send_approve(client, accepted_connection, accepted_connection["founder_headers"], msg)
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    assert isinstance(r["memory"]["key_themes"], list)


def test_memory_stable(client, accepted_connection):
    _send_approve(client, accepted_connection, accepted_connection["founder_headers"], "a stable thought")
    a = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()["memory"]
    b = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()["memory"]
    assert a == b
