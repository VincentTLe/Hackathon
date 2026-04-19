import os
import uuid

import httpx
import pytest

DEFAULT_URL = "https://hackathon-production-97f9.up.railway.app"


@pytest.fixture(scope="session")
def api_url() -> str:
    return os.environ.get("BRIDGE_TEST_URL", DEFAULT_URL).rstrip("/")


@pytest.fixture
def client(api_url):
    with httpx.Client(base_url=api_url, timeout=60.0) as c:
        yield c


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def founder(client):
    payload = {
        "name": _uniq("Founder"),
        "answers": [
            "I struggle to say what I need without sounding harsh.",
            "My mother takes criticism personally.",
            "I want her to hear my care under the words.",
            "We don't talk about money easily.",
            "I get quiet when I feel judged.",
        ],
    }
    r = client.post("/onboarding/founder", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    data["headers"] = {"Authorization": f"Bearer {data['founder_token']}"}
    data["name"] = payload["name"]
    return data


@pytest.fixture
def connection(client, founder):
    r = client.post(
        "/connections",
        json={
            "receiver_display_name": _uniq("Mom"),
            "relationship": "mother",
            "invite_note": "Hi mom",
        },
        headers=founder["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def accepted_connection(client, founder, connection):
    r = client.post(
        "/session/b-accept",
        json={
            "magic_link_token": connection["magic_link_token"],
            "receiver_name": _uniq("Receiver"),
        },
    )
    assert r.status_code == 200, r.text
    sess = r.json()
    return {
        "founder": founder,
        "connection_id": connection["connection_id"],
        "magic_link_token": connection["magic_link_token"],
        "session_token": sess["session_token"],
        "receiver_headers": {"Authorization": f"Bearer {sess['session_token']}"},
        "founder_headers": founder["headers"],
    }
