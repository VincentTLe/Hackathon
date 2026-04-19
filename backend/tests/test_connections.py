def _body(name="Mom", rel="mother", note=""):
    return {"receiver_display_name": name, "relationship": rel, "invite_note": note}


def test_create_no_auth(client):
    r = client.post("/connections", json=_body())
    assert r.status_code == 401


def test_create_bad_token(client):
    r = client.post("/connections", json=_body(), headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401


def test_create_happy(client, founder):
    r = client.post("/connections", json=_body(), headers=founder["headers"])
    assert r.status_code == 200
    d = r.json()
    assert d["connection_id"]
    assert d["magic_link_token"]
    assert d["magic_link_token"] in d["magic_link_url"]


def test_list_includes_created(client, founder, connection):
    r = client.get("/connections", headers=founder["headers"])
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["connections"]]
    assert connection["connection_id"] in ids


def test_unaccepted_flag(client, founder, connection):
    r = client.get("/connections", headers=founder["headers"])
    item = next(c for c in r.json()["connections"] if c["id"] == connection["connection_id"])
    assert item["accepted"] is False


def test_two_connections_different_links(client, founder):
    a = client.post("/connections", json=_body(), headers=founder["headers"]).json()
    b = client.post("/connections", json=_body(), headers=founder["headers"]).json()
    assert a["magic_link_token"] != b["magic_link_token"]


def test_create_missing_name(client, founder):
    r = client.post(
        "/connections",
        json={"relationship": "mother"},
        headers=founder["headers"],
    )
    assert r.status_code == 422


def test_invite_note_optional(client, founder):
    r = client.post(
        "/connections",
        json={"receiver_display_name": "X", "relationship": "y"},
        headers=founder["headers"],
    )
    assert r.status_code == 200
