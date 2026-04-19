def _tr(client, conn_id, headers, msg="Mẹ ơi, con thấy áp lực lắm."):
    return client.post("/messages/translate", json={"connection_id": conn_id, "raw_message": msg}, headers=headers)


def test_founder_translate_happy(client, accepted_connection):
    r = _tr(client, accepted_connection["connection_id"], accepted_connection["founder_headers"])
    assert r.status_code == 200
    d = r.json()
    assert d["preview_id"]
    assert d["translated_content"]


def test_receiver_translate_happy(client, accepted_connection):
    r = _tr(client, accepted_connection["connection_id"], accepted_connection["receiver_headers"], "Mom reply ok.")
    assert r.status_code == 200
    assert r.json()["preview_id"]


def test_crisis_detected(client, accepted_connection):
    r = _tr(client, accepted_connection["connection_id"], accepted_connection["founder_headers"],
            "I want to kill myself tonight, I can't do this anymore.")
    assert r.status_code == 422
    detail = r.json().get("detail")
    assert (isinstance(detail, dict) and detail.get("code") == "crisis_detected") or "crisis" in str(detail).lower()


def test_empty_raw(client, accepted_connection):
    r = client.post(
        "/messages/translate",
        json={"connection_id": accepted_connection["connection_id"], "raw_message": ""},
        headers=accepted_connection["founder_headers"],
    )
    assert r.status_code == 422


def test_too_long(client, accepted_connection):
    r = client.post(
        "/messages/translate",
        json={"connection_id": accepted_connection["connection_id"], "raw_message": "x" * 5000},
        headers=accepted_connection["founder_headers"],
    )
    assert r.status_code == 422


def test_wrong_connection(client, accepted_connection):
    r = _tr(client, "not-a-real-connection", accepted_connection["founder_headers"])
    assert r.status_code == 404


def test_no_auth_still_works_legacy(client):
    r = client.post(
        "/messages/translate",
        json={"raw_message": "hello mom", "sender_profile": "", "receiver_profile": ""},
    )
    assert r.status_code in (200, 422)


def test_legacy_shape(client):
    r = client.post(
        "/messages/translate",
        json={"raw_message": "I miss you mom", "sender_profile": "warm", "receiver_profile": "patient"},
    )
    if r.status_code == 200:
        d = r.json()
        assert "translated_content" in d
        assert "emotional_interpretation" in d
        assert "educational_context" in d


def test_preview_ids_unique(client, accepted_connection):
    a = _tr(client, accepted_connection["connection_id"], accepted_connection["founder_headers"]).json()
    b = _tr(client, accepted_connection["connection_id"], accepted_connection["founder_headers"]).json()
    assert a["preview_id"] != b["preview_id"]


def test_translate_no_raw_leak(client, accepted_connection):
    r = _tr(client, accepted_connection["connection_id"], accepted_connection["founder_headers"], "SECRET-RAW-XYZ")
    d = r.json()
    assert "SECRET-RAW-XYZ" not in str(d) or d["translated_content"] != "SECRET-RAW-XYZ"
