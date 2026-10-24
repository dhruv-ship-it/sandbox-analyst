def test_health_reports_status_version_provider_model_sandbox(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "fake"
    assert body["sandbox"] == "fake"
    assert "version" in body


def test_health_never_leaks_secrets_or_budget_figures(client):
    body = client.get("/api/health").json()
    text = str(body).lower()
    for forbidden in ("key", "secret", "token", "budget", "usd"):
        assert forbidden not in text


def test_placeholder_page_served_when_no_web_dist(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Sandbox Analyst" in response.text
    assert "UI coming soon" in response.text
    assert "/api/health" in response.text


def test_security_headers_present(client):
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_unknown_api_route_is_a_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]
    assert body["detail"]
