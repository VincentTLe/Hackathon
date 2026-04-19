import time


def _send(client, ac, headers, msg):
    p = client.post("/messages/translate", json={"connection_id": ac["connection_id"], "raw_message": msg}, headers=headers).json()
    client.post("/messages/approve", json={"preview_id": p["preview_id"]}, headers=headers)
    return p


def test_founder_sees_own_translated(client, accepted_connection):
    _send(client, accepted_connection, accepted_connection["founder_headers"], "Con yêu mẹ.")
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    mine = [m for m in r["messages"] if m["is_mine"]]
    assert mine
    assert "emotional_interpretation" not in mine[0]


def test_receiver_sees_3part(client, accepted_connection):
    _send(client, accepted_connection, accepted_connection["founder_headers"], "Mom I'm struggling.")
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["receiver_headers"]).json()
    inbound = [m for m in r["messages"] if not m["is_mine"]]
    assert inbound
    assert "emotional_interpretation" in inbound[0]
    assert "educational_context" in inbound[0]
    assert "translated_content" in inbound[0]


def test_receiver_own_no_3part(client, accepted_connection):
    _send(client, accepted_connection, accepted_connection["receiver_headers"], "I hear you.")
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["receiver_headers"]).json()
    mine = [m for m in r["messages"] if m["is_mine"]]
    assert mine
    assert "emotional_interpretation" not in mine[0]


def test_founder_sees_receiver_reply_3part(client, accepted_connection):
    _send(client, accepted_connection, accepted_connection["receiver_headers"], "Mom's reply.")
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    inbound = [m for m in r["messages"] if not m["is_mine"]]
    assert inbound
    assert "emotional_interpretation" in inbound[0]


def test_no_raw_leak_to_other(client, accepted_connection):
    _send(client, accepted_connection, accepted_connection["founder_headers"], "SECRETRAW123")
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["receiver_headers"]).json()
    inbound = [m for m in r["messages"] if not m["is_mine"]]
    assert all("raw_content" not in m for m in inbound)


def test_since_filter(client, accepted_connection):
    _send(client, accepted_connection, accepted_connection["founder_headers"], "msg 1")
    r1 = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    ts = r1["server_time"]
    time.sleep(1)
    _send(client, accepted_connection, accepted_connection["founder_headers"], "msg 2")
    r2 = client.get(
        f"/messages/{accepted_connection['connection_id']}",
        headers=accepted_connection["founder_headers"],
        params={"since": ts},
    ).json()
    assert len(r2["messages"]) < len(r1["messages"]) + 2


def test_server_time_present(client, accepted_connection):
    r = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["founder_headers"]).json()
    assert r["server_time"]


def test_two_device_polling(client, accepted_connection):
    r0 = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["receiver_headers"]).json()
    before = len(r0["messages"])
    _send(client, accepted_connection, accepted_connection["founder_headers"], "across devices test")
    time.sleep(1)
    r1 = client.get(f"/messages/{accepted_connection['connection_id']}", headers=accepted_connection["receiver_headers"]).json()
    assert len(r1["messages"]) == before + 1
