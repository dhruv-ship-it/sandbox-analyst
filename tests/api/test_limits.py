from sandbox_analyst.api.limits import (
    RateLimiter,
    client_ip,
    forwarded_client_ip,
    parse_forwarded_entry,
)

# ---- pure helpers ----


def test_parse_forwarded_entry_plain_ipv4():
    assert parse_forwarded_entry("203.0.113.5") == "203.0.113.5"


def test_parse_forwarded_entry_ipv4_with_port():
    assert parse_forwarded_entry("203.0.113.5:51234") == "203.0.113.5"


def test_parse_forwarded_entry_ipv6_bracketed_with_port():
    assert parse_forwarded_entry("[2001:db8::1]:443") == "2001:db8::1"


def test_parse_forwarded_entry_ipv6_bare():
    assert parse_forwarded_entry("2001:db8::1") == "2001:db8::1"


def test_parse_forwarded_entry_garbage_is_none():
    assert parse_forwarded_entry("not-an-ip") is None


def test_forwarded_client_ip_reads_the_rightmost_entry():
    # A caller sending a forged left entry just gets their real address
    # appended after it by the trusted proxy; the right-most entry is real.
    header = "1.2.3.4, 203.0.113.9"
    assert forwarded_client_ip(header) == "203.0.113.9"


def test_forwarded_client_ip_missing_header_is_none():
    assert forwarded_client_ip(None) is None
    assert forwarded_client_ip("") is None


# ---- RateLimiter ----


def test_rate_limiter_allows_up_to_the_concurrency_cap_then_busy():
    limiter = RateLimiter(per_ip_hour=100, per_ip_day=100, global_day=100, max_concurrent=2)
    assert limiter.reserve("1.1.1.1") is None
    assert limiter.reserve("2.2.2.2") is None
    reason = limiter.reserve("3.3.3.3")
    assert reason is not None and "busy" in reason
    limiter.release()
    assert limiter.reserve("3.3.3.3") is None


def test_rate_limiter_per_ip_hourly_cap():
    limiter = RateLimiter(per_ip_hour=2, per_ip_day=100, global_day=100, max_concurrent=100)
    assert limiter.reserve("1.1.1.1") is None
    assert limiter.reserve("1.1.1.1") is None
    reason = limiter.reserve("1.1.1.1")
    assert reason is not None and "hour" in reason
    # A different IP is unaffected.
    assert limiter.reserve("2.2.2.2") is None


def test_rate_limiter_per_ip_daily_cap():
    limiter = RateLimiter(per_ip_hour=100, per_ip_day=2, global_day=100, max_concurrent=100)
    assert limiter.reserve("1.1.1.1") is None
    assert limiter.reserve("1.1.1.1") is None
    reason = limiter.reserve("1.1.1.1")
    assert reason is not None and "day" in reason


def test_rate_limiter_global_daily_cap():
    limiter = RateLimiter(per_ip_hour=100, per_ip_day=100, global_day=2, max_concurrent=100)
    assert limiter.reserve("1.1.1.1") is None
    assert limiter.reserve("2.2.2.2") is None
    reason = limiter.reserve("3.3.3.3")
    assert reason is not None and "daily cap" in reason


def test_rate_limiter_reset_forgets_everything():
    limiter = RateLimiter(per_ip_hour=1, per_ip_day=100, global_day=100, max_concurrent=100)
    limiter.reserve("1.1.1.1")
    assert limiter.reserve("1.1.1.1") is not None
    limiter.reset()
    assert limiter.reserve("1.1.1.1") is None


# ---- client_ip() / X-Forwarded-For wiring, via a minimal fake Request ----


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, peer: str, headers: dict[str, str]) -> None:
        self.client = _FakeClient(peer)
        self.headers = headers


def test_client_ip_ignores_header_when_not_trusting_proxy():
    request = _FakeRequest("1.2.3.4", {"x-forwarded-for": "9.9.9.9"})
    assert client_ip(request, trust_proxy=False) == "1.2.3.4"


def test_client_ip_uses_header_when_trusting_proxy():
    request = _FakeRequest("1.2.3.4", {"x-forwarded-for": "9.9.9.9"})
    assert client_ip(request, trust_proxy=True) == "9.9.9.9"


def test_client_ip_falls_back_to_peer_when_trusting_proxy_but_no_header():
    request = _FakeRequest("1.2.3.4", {})
    assert client_ip(request, trust_proxy=True) == "1.2.3.4"


# ---- end-to-end wiring through the API ----


def test_api_enforces_per_ip_hourly_limit(build_client, load_sales_dataset):
    client = build_client(sa_rate_limit_per_ip_hour=1)
    dataset_id = load_sales_dataset(client)
    first = client.post(
        "/api/runs", json={"dataset_id": dataset_id, "question": "what is the total?"}
    )
    assert first.status_code == 200
    second = client.post(
        "/api/runs", json={"dataset_id": dataset_id, "question": "what is the total?"}
    )
    assert second.status_code == 429
    assert second.json()["error"] == "rate_limited"


def test_api_trusts_x_forwarded_for_only_when_configured(build_client, load_sales_dataset):
    client = build_client(
        sa_rate_limit_per_ip_hour=1, sa_trust_proxy=True, client_addr=("5.5.5.5", 1)
    )
    dataset_id = load_sales_dataset(client)

    first = client.post(
        "/api/runs",
        json={"dataset_id": dataset_id, "question": "what is the total?"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert first.status_code == 200

    # A different forwarded IP, same socket peer, is a different bucket.
    second = client.post(
        "/api/runs",
        json={"dataset_id": dataset_id, "question": "what is the total?"},
        headers={"X-Forwarded-For": "8.8.8.8"},
    )
    assert second.status_code == 200

    # Re-using the first forwarded IP hits its own (now exhausted) limit.
    third = client.post(
        "/api/runs",
        json={"dataset_id": dataset_id, "question": "what is the total?"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert third.status_code == 429


def test_api_ignores_x_forwarded_for_when_not_trusting_proxy(build_client, load_sales_dataset):
    client = build_client(
        sa_rate_limit_per_ip_hour=1, sa_trust_proxy=False, client_addr=("5.5.5.5", 1)
    )
    dataset_id = load_sales_dataset(client)

    first = client.post(
        "/api/runs",
        json={"dataset_id": dataset_id, "question": "what is the total?"},
        headers={"X-Forwarded-For": "9.9.9.9"},
    )
    assert first.status_code == 200

    # Different forwarded header, SAME socket peer: still the same bucket, since
    # the header is untrusted here -- so this is the second run from "5.5.5.5".
    second = client.post(
        "/api/runs",
        json={"dataset_id": dataset_id, "question": "what is the total?"},
        headers={"X-Forwarded-For": "8.8.8.8"},
    )
    assert second.status_code == 429
