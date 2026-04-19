def _payload(name="Test User", n=5):
    return {"name": name, "answers": [f"answer {i}" for i in range(n)]}


def test_onboard_happy(client):
    r = client.post("/onboarding/founder", json=_payload())
    assert r.status_code == 200
    d = r.json()
    assert d["founder_id"]
    assert len(d["founder_token"]) >= 32
    assert "communication_profile" in d
    assert "receiver_seed_profile" in d


def test_onboard_missing_name(client):
    r = client.post("/onboarding/founder", json={"answers": ["a"]})
    assert r.status_code == 422


def test_onboard_empty_answers(client):
    r = client.post("/onboarding/founder", json={"name": "X", "answers": []})
    assert r.status_code == 422


def test_onboard_one_answer_ok(client):
    r = client.post("/onboarding/founder", json={"name": "X", "answers": ["only one"]})
    assert r.status_code == 200


def test_onboard_many_answers_ok(client):
    r = client.post("/onboarding/founder", json=_payload(n=10))
    assert r.status_code == 200


def test_onboard_empty_name(client):
    r = client.post("/onboarding/founder", json={"name": "", "answers": ["a"]})
    assert r.status_code == 422


def test_onboard_token_unique(client):
    a = client.post("/onboarding/founder", json=_payload()).json()
    b = client.post("/onboarding/founder", json=_payload()).json()
    assert a["founder_token"] != b["founder_token"]


def test_onboard_profile_is_dict(client):
    d = client.post("/onboarding/founder", json=_payload()).json()
    assert isinstance(d["communication_profile"], dict)
    assert isinstance(d["receiver_seed_profile"], dict)
