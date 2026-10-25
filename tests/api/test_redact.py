from sandbox_analyst.api.redact import redact_secrets
from sandbox_analyst.config import Settings


def test_redacts_a_modal_style_prefix():
    text = redact_secrets("token ak-1234567890abcdef leaked")
    assert "ak-1234567890abcdef" not in text
    assert "[redacted]" in text


def test_redacts_a_groq_style_prefix():
    text = redact_secrets("key gsk_abc123XYZ exposed")
    assert "gsk_abc123XYZ" not in text
    assert "[redacted]" in text


def test_redacts_an_nvidia_style_prefix():
    text = redact_secrets("nvapi-deadbeef1234 in the message")
    assert "nvapi-deadbeef1234" not in text
    assert "[redacted]" in text


def test_leaves_ordinary_text_alone():
    text = redact_secrets("a plain error message with no secrets")
    assert text == "a plain error message with no secrets"


def test_redacts_a_configured_secret_setting_value_even_without_a_known_prefix():
    settings = Settings(groq_api_key="totally-custom-value-123")
    text = redact_secrets("provider said totally-custom-value-123 is invalid", settings)
    assert "totally-custom-value-123" not in text
    assert "[redacted]" in text


def test_an_unset_secret_setting_redacts_nothing_extra():
    settings = Settings(groq_api_key=None)
    text = redact_secrets("no secret configured here", settings)
    assert text == "no secret configured here"


def test_no_settings_still_redacts_known_prefixes():
    text = redact_secrets("as-shouldbemasked123")
    assert "as-shouldbemasked123" not in text
    assert "[redacted]" in text
