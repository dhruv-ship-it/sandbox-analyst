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


def test_placeholder_page_served_when_no_web_dist(monkeypatch, build_client, tmp_path):
    import sandbox_analyst.api.app as app_module

    # Hermetic regardless of whether a real `web/dist` build happens to
    # exist on disk (it does, once web/ has been built -- see docs/ui.md).
    monkeypatch.setattr(app_module, "WEB_DIST_DIR", tmp_path / "no-such-dist")
    client = build_client()

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Sandbox Analyst" in response.text
    assert "UI coming soon" in response.text
    assert "/api/health" in response.text


def test_built_web_dist_is_served_when_present(monkeypatch, build_client, tmp_path):
    import sandbox_analyst.api.app as app_module

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<!doctype html><title>built ui</title>")
    monkeypatch.setattr(app_module, "WEB_DIST_DIR", dist_dir)
    client = build_client()

    response = client.get("/")
    assert response.status_code == 200
    assert "built ui" in response.text


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
