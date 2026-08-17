from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_session_manager.config import AppPaths
from codex_session_manager.hashing import sealed_fingerprint, utc_now
from codex_session_manager.review_requests import (
    ReviewOperation,
    ReviewRequest,
    ReviewRequestQueue,
    ReviewRequestStore,
    ReviewSource,
    SuggestedAction,
    SuggestionBundle,
    SuggestionBundleStore,
    SuggestionTarget,
    codex_account_fingerprint,
)


def _paths(tmp_path: Path, *, codex_name: str = "codex") -> AppPaths:
    data = tmp_path / "data"
    return AppPaths(
        data_dir=data,
        config_dir=tmp_path / "config",
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "log",
        plans_dir=data / "plans",
        imports_dir=data / "imports",
        backups_dir=data / "backups",
        audit_db=data / "audit.sqlite3",
        codex_home=tmp_path / codex_name,
    )


def test_review_request_and_suggestion_round_trip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    target = SuggestionTarget(
        target_id="thread-1",
        source_fingerprint="content-sha",
        suggested_action=SuggestedAction.ARCHIVE,
        reason="长期未活动",
        confidence=0.91,
    )
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        targets=(target,),
    )
    bundle_path = SuggestionBundleStore(paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONVERSATION_CLEANUP,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
        suggestion_bundle_path=bundle_path,
    )
    request_path = ReviewRequestStore(paths).save(request)

    assert request_path.stat().st_mode & 0o777 == 0o600
    assert ReviewRequestStore(paths).load(request_path) == request
    assert SuggestionBundleStore(paths).load(bundle_path) == bundle


def test_review_request_rejects_tamper_expiry_and_account_drift(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.SKILL,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
    )
    tampered = request.model_copy(update={"target_ids": ("thread-2",)})
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        tampered.verify()

    expired = request.model_copy(
        update={"expires_at": utc_now() - timedelta(seconds=1), "request_sha256": ""}
    )
    expired = expired.model_copy(
        update={"request_sha256": sealed_fingerprint(expired, "request_sha256")}
    )
    with pytest.raises(ValueError, match="expired"):
        expired.verify()

    request_path = ReviewRequestStore(paths).save(request)
    other_paths = _paths(tmp_path, codex_name="other-codex")
    other_paths.ensure()
    copied = other_paths.review_requests_dir / request_path.name
    copied.write_bytes(request_path.read_bytes())
    with pytest.raises(ValueError, match="another Codex account root"):
        ReviewRequestStore(other_paths).load(copied)


def test_review_store_rejects_path_escape_and_symlink(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.CLI,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
    )
    request_path = ReviewRequestStore(paths).save(request)
    escaped = tmp_path / request_path.name
    escaped.write_bytes(request_path.read_bytes())
    with pytest.raises(ValueError, match="escaped"):
        ReviewRequestStore(paths).load(escaped)

    link = paths.review_requests_dir / "review-link.json"
    try:
        link.symlink_to(request_path)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this platform")
    with pytest.raises(ValueError, match="symbolic link"):
        ReviewRequestStore(paths).load(link)


def test_suggestion_actions_are_scoped_by_operation() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        SuggestionBundle.create(
            operation=ReviewOperation.CONVERSATION_CLEANUP,
            source=ReviewSource.MCP,
            targets=(
                SuggestionTarget(
                    target_id="thread-1",
                    source_fingerprint="content-sha",
                    suggested_action=SuggestedAction.DELETE,
                    reason="不允许把永久删除作为普通清理建议",
                    confidence=0.5,
                ),
            ),
        )

    with pytest.raises(ValidationError, match="requires suggested_text"):
        SuggestionTarget(
            target_id="turn-1",
            source_fingerprint="content-sha",
            suggested_action=SuggestedAction.SUMMARY,
            reason="建议摘要",
            confidence=0.8,
        )


def test_request_scope_rejects_wrong_target_kind(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(ValidationError, match="exactly one conversation id"):
        ReviewRequest.create(
            operation=ReviewOperation.CONTEXT_TRIM,
            source=ReviewSource.CLI,
            account_root_fingerprint=codex_account_fingerprint(paths),
            target_ids=("one", "two"),
        )
    with pytest.raises(ValidationError, match="does not accept conversation ids"):
        ReviewRequest.create(
            operation=ReviewOperation.MEMORY_EDIT,
            source=ReviewSource.CLI,
            account_root_fingerprint=codex_account_fingerprint(paths),
            target_ids=("thread-1",),
        )


def test_review_request_queue_is_idempotent_and_acknowledged(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.SKILL,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
    )
    request_path = ReviewRequestStore(paths).save(request)
    queue = ReviewRequestQueue(paths)

    queued_request, pending_path = queue.enqueue(request_path)
    second_request, second_path = queue.enqueue(request_path)

    assert queued_request == request
    assert second_request == request
    assert second_path == pending_path
    assert pending_path.stat().st_mode & 0o777 == 0o600
    assert queue.load_request(pending_path) == request
    assert queue.entry_paths() == (pending_path,)

    queue.acknowledge(request)
    assert not pending_path.exists()
    queue.acknowledge(request)


def test_review_identifiers_reject_path_control_characters(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.CLI,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
    )
    payload = request.model_dump(mode="json")
    payload["request_id"] = "../escaped"

    with pytest.raises(ValidationError, match="request_id"):
        ReviewRequest.model_validate(payload)


def test_context_request_accepts_turn_suggestions_but_rejects_file_targets(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_id="turn-1",
                source_fingerprint="turn-fingerprint",
                suggested_action=SuggestedAction.KEEP,
                reason="保留该 turn",
                confidence=0.8,
            ),
        ),
    )
    bundle_path = SuggestionBundleStore(paths).save(bundle)
    request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
        suggestion_bundle_path=bundle_path,
    )
    request_path = ReviewRequestStore(paths).save(request)

    assert ReviewRequestStore(paths).load(request_path) == request

    invalid_bundle = SuggestionBundle.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        targets=(
            SuggestionTarget(
                target_path="MEMORY.md",
                source_fingerprint="file-fingerprint",
                suggested_action=SuggestedAction.KEEP,
                reason="错误的目标类型",
                confidence=0.1,
            ),
        ),
    )
    invalid_path = SuggestionBundleStore(paths).save(invalid_bundle)
    invalid_request = ReviewRequest.create(
        operation=ReviewOperation.CONTEXT_TRIM,
        source=ReviewSource.MCP,
        account_root_fingerprint=codex_account_fingerprint(paths),
        target_ids=("thread-1",),
        suggestion_bundle_path=invalid_path,
    )
    invalid_request_path = ReviewRequestStore(paths).save(invalid_request)

    with pytest.raises(ValueError, match="turn or item ids"):
        ReviewRequestStore(paths).load(invalid_request_path)
