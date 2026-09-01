from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_session_manager.config import AppPaths
from codex_session_manager.models import (
    CapabilityMatrix,
    ContractMethodEvidence,
    ItemKind,
    OperationCapability,
    OperationName,
    ThreadHistoryMode,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TurnSnapshot,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
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
        codex_home=tmp_path / "codex-home",
    )


@pytest.fixture
def operation_capabilities() -> tuple[OperationCapability, ...]:
    methods = {
        OperationName.INVENTORY_COMMON: (
            "initialize",
            "thread/list",
            "thread/read",
            "thread/loaded/list",
        ),
        OperationName.HISTORY_LEGACY: ("thread/read",),
        OperationName.HISTORY_PAGINATED: ("thread/turns/list",),
        OperationName.ARCHIVE: ("thread/archive",),
        OperationName.UNARCHIVE: ("thread/unarchive",),
    }
    return tuple(
        OperationCapability(
            operation=operation,
            contract_id=f"{operation.value}.v1",
            available=True,
            contract_rule_fingerprint=f"rule-{operation.value}",
            runtime_contract_fingerprint=f"runtime-{operation.value}",
            required_methods=required_methods,
            method_evidence=tuple(
                ContractMethodEvidence(
                    method=method,
                    stability="stable",
                    negotiated=False,
                )
                for method in required_methods
            ),
        )
        for operation, required_methods in methods.items()
    )


@pytest.fixture
def capabilities(operation_capabilities) -> CapabilityMatrix:
    return CapabilityMatrix(
        codex_version="test-codex",
        codex_binary_path="/test/codex",
        codex_binary_sha256="a" * 64,
        initialize_fingerprint="init",
        schema_sha256="b" * 64,
        stable_methods=tuple(
            sorted(
                {
                    "initialize",
                    "thread/list",
                    "thread/read",
                    "thread/loaded/list",
                    "thread/turns/list",
                    "thread/archive",
                    "thread/unarchive",
                }
            )
        ),
        experimental_methods=(),
        experimental_api=True,
        schema_complete=True,
        operation_capabilities=operation_capabilities,
    )


@pytest.fixture
def snapshot_factory() -> Callable[..., ThreadSnapshot]:
    def create(
        thread_id: str = "thread-1",
        *,
        archived: bool = False,
        pinned: bool = False,
        status: ThreadStatus = ThreadStatus.IDLE,
        parent_id: str | None = None,
        updated_at: datetime | None = None,
        turns: tuple[TurnSnapshot, ...] | None = None,
        content_complete: bool = True,
        ephemeral: bool = False,
        history_mode: ThreadHistoryMode = ThreadHistoryMode.LEGACY,
    ) -> ThreadSnapshot:
        if turns is None:
            item = ThreadItemSnapshot(
                id=f"{thread_id}-item",
                turn_id=f"{thread_id}-turn",
                kind=ItemKind.ASSISTANT_MESSAGE,
                raw_type="agentMessage",
                role="assistant",
                text=f"content for {thread_id}",
                token_estimate=5,
            )
            turns = (TurnSnapshot(id=f"{thread_id}-turn", status="completed", items=(item,)),)
        return ThreadSnapshot(
            id=thread_id,
            title=thread_id,
            cwd="/tmp/project",
            updated_at=updated_at or datetime(2025, 1, 1, tzinfo=UTC),
            status=status,
            archived=archived,
            pinned=pinned,
            ephemeral=ephemeral,
            parent_id=parent_id,
            turns=turns,
            content_complete=content_complete,
            history_mode=history_mode,
        )

    return create
