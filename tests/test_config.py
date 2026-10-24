from sandbox_analyst.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.sa_sandbox == "fake"
    assert s.sa_sandbox_budget_usd == 0.80
    assert s.sandbox_cpu == 0.25
    assert s.sandbox_memory_mib == 1024
    assert s.sandbox_memory_hard_limit_mib == 2048
    assert s.sandbox_lifetime_s == 120
    assert s.run_timeout_s == 30
    assert s.max_upload_mb == 25
    assert s.usd_per_core_second == 0.00003942
    assert s.usd_per_gib_second == 0.00000667


def test_extra_env_keys_are_ignored():
    s = Settings(_env_file=None, SOME_UNRELATED_KEY="x")
    assert not hasattr(s, "some_unrelated_key")


def test_secrets_never_leak_in_repr_or_str():
    s = Settings(_env_file=None, nim_api_key="super-secret-nim", groq_api_key="super-secret-groq")
    assert "super-secret-nim" not in repr(s)
    assert "super-secret-nim" not in str(s)
    assert "super-secret-groq" not in repr(s)
    assert "super-secret-groq" not in str(s)
    assert s.nim_api_key.get_secret_value() == "super-secret-nim"
    assert s.groq_api_key.get_secret_value() == "super-secret-groq"


def test_secrets_default_to_none():
    s = Settings(_env_file=None)
    assert s.nim_api_key is None
    assert s.groq_api_key is None
