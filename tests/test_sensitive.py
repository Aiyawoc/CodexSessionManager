import pytest

from codex_session_manager.models import ItemKind, ThreadItemSnapshot, TurnSnapshot
from codex_session_manager.sensitive import (
    SensitiveScanCancelled,
    SensitiveSeverity,
    scan_sensitive_snapshot,
    scan_sensitive_text,
)


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


def test_snapshot_scanner_aggregates_without_retaining_spans_and_can_cancel(
    snapshot_factory,
) -> None:
    secret = "sk-proj-1234567890abcdefghijkl"
    items = tuple(
        ThreadItemSnapshot(
            id=f"item-{index}",
            turn_id="turn-1",
            kind=ItemKind.USER_MESSAGE,
            raw_type="userMessage",
            role="user",
            text=f"part {index}: {secret}",
            token_estimate=10,
        )
        for index in range(2)
    )
    snapshot = snapshot_factory(
        "batch-sensitive",
        turns=(TurnSnapshot(id="turn-1", status="completed", items=items),),
    )

    result = scan_sensitive_snapshot(snapshot)

    finding = next(item for item in result.findings if item.category == "云服务/API 密钥")
    assert finding.count == 2
    assert not result.spans

    split_assignment = snapshot_factory(
        "split-assignment",
        turns=(
            TurnSnapshot(
                id="turn-1",
                status="completed",
                items=(
                    items[0].model_copy(update={"text": "password ="}),
                    items[1].model_copy(update={"text": "supersecretvalue"}),
                ),
            ),
        ),
    ).model_copy(update={"title": "", "preview": ""})
    split_result = scan_sensitive_snapshot(split_assignment)
    split_finding = next(item for item in split_result.findings if item.category == "口令/令牌赋值")
    assert split_finding.count == 1

    large_item = items[0].model_copy(
        update={"text": "x" * (256 * 1024 - 8) + f" {secret} " + "x" * 32}
    )
    large_snapshot = snapshot_factory(
        "large-batch-sensitive",
        turns=(TurnSnapshot(id="turn-1", status="completed", items=(large_item,)),),
    ).model_copy(update={"title": "", "preview": ""})
    boundary_result = scan_sensitive_snapshot(large_snapshot)
    boundary_finding = next(
        item for item in boundary_result.findings if item.category == "云服务/API 密钥"
    )
    assert boundary_finding.count == 1

    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 2

    with pytest.raises(SensitiveScanCancelled):
        scan_sensitive_snapshot(large_snapshot, cancelled=cancelled)
    assert checks == 3
