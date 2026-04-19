def test_cors_preflight_vercel(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://hackathon-rho-nine-81.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)
    assert "access-control-allow-origin" in {k.lower() for k in r.headers.keys()}


def test_cors_preflight_localhost(client):
    r = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code in (200, 204)


def test_404_json(client):
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert "application/json" in r.headers.get("content-type", "")


def test_422_shape(client):
    r = client.post("/onboarding/founder", json={})
    assert r.status_code == 422
    assert "detail" in r.json()


def test_401_consistent(client):
    r = client.get("/connections")
    assert r.status_code == 401
    assert "application/json" in r.headers.get("content-type", "")


def test_2xx_json(client):
    r = client.get("/health")
    assert "application/json" in r.headers.get("content-type", "")
