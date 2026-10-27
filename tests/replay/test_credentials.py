from sandbox_analyst.replay.credentials import (
    CREDENTIAL_PATTERNS,
    scan_cassette_files,
    scan_text_for_credentials,
)


def test_clean_text_has_no_findings():
    assert scan_text_for_credentials("just a normal response about sales totals") == []


def test_each_known_pattern_is_detected():
    for pattern in CREDENTIAL_PATTERNS:
        text = f"some text before {pattern}abcdef1234567890 and after"
        findings = scan_text_for_credentials(text)
        assert findings, f"expected a finding for pattern {pattern!r}"


def test_scan_cassette_files_reports_the_path(tmp_path):
    leaky = tmp_path / "leaky.jsonl"
    leaky.write_text('{"key":"gsk_abcdef1234567890"}', encoding="utf-8")
    clean = tmp_path / "clean.jsonl"
    clean.write_text('{"key":"nothing secret here"}', encoding="utf-8")
    missing = tmp_path / "does_not_exist.jsonl"

    findings = scan_cassette_files([leaky, clean, missing])

    assert len(findings) == 1
    assert str(leaky) in findings[0]
