from codex_session_manager.sensitive import SensitiveSeverity, scan_sensitive_text


def test_sensitive_scanner_returns_redacted_categories_only() -> None:
    secret = "sk-proj-1234567890abcdefghijkl"
    source = f"token={secret}\ncontact user@example.com\ncard 4111 1111 1111 1111"
    result = scan_sensitive_text(source)

    assert result.has_findings
    assert result.maximum_severity is SensitiveSeverity.HIGH
    assert "云服务/API 密钥" in result.summary
    assert "电子邮箱" in result.summary
    assert "支付卡号" in result.summary
    assert secret not in repr(result)
    assert secret not in result.summary
    assert any(
        source[span.start : span.end] == secret or secret in source[span.start : span.end]
        for span in result.spans
    )
    assert all(secret not in repr(span) for span in result.spans)


def test_sensitive_scanner_ignores_placeholders_and_invalid_numbers() -> None:
    result = scan_sensitive_text(
        "api_key=${API_KEY}\npassword=<redacted>\nemail=user@example\n4111111111111112"
    )

    assert not result.has_findings
    assert not result.spans
