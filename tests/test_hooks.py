from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from codex_session_manager.hashing import utc_now
from codex_session_manager.hooks import (
    HookDecision,
    HookDecisionStore,
    HookHandler,
    HookInput,
    HookInstaller,
    HookOutput,
)
from codex_session_manager.models import TrimAction, TrimPlan, TrimSelection


def _hook_input() -> dict[str, object]:
    return {
        "session_id": "session-1",
        "transcript_path": None,
        "cwd": "/tmp/project",
        "hook_event_name": "PreCompact",
        "model": "gpt-test",
        "turn_id": "turn-1",
        "trigger": "auto",
    }


def test_precompact_blocks_only_after_plan_is_persisted(
    app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("session-1")
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(
            TrimSelection(
                target_id=snapshot.turns[0].id,
                action=TrimAction.KEEP,
            ),
        ),
        estimated_tokens_after=snapshot.token_estimate,
        trigger="hook",
        source_turn_id="turn-1",
    )
    reviews = 0

    def reviewer(_input, _deadline):
        nonlocal reviews
        reviews += 1
        return plan

    handler = HookHandler(app_paths, reviewer=reviewer)
    first = handler.precompact(_hook_input())
    second = handler.precompact(_hook_input())
    assert first.continue_ is False
    assert second.continue_ is False
    assert reviews == 1
    decision_files = tuple((app_paths.data_dir / "hook-decisions").glob("*.json"))
    assert len(decision_files) == 1
    assert tuple(app_paths.plans_dir.glob("trim-*.json"))


def test_precompact_is_fail_open_for_cancel_and_concurrent_duplicate(
    app_paths,
) -> None:
    handler = HookHandler(app_paths, reviewer=lambda _input, _deadline: None)
    cancelled = handler.precompact(_hook_input())
    assert cancelled.continue_ is True

    other = HookHandler(app_paths, reviewer=lambda _input, _deadline: None)
    with other.decisions.try_lock() as lock:
        assert lock is not None
        started = time.monotonic()
        concurrent = handler.precompact(_hook_input() | {"session_id": "another-session"})
    assert concurrent.continue_ is True
    assert time.monotonic() - started < 1


def test_precompact_rejects_tampered_cached_plan(app_paths, capabilities, snapshot_factory) -> None:
    snapshot = snapshot_factory("session-1")
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(TrimSelection(target_id=snapshot.turns[0].id, action=TrimAction.KEEP),),
        estimated_tokens_after=snapshot.token_estimate,
        trigger="hook",
        source_turn_id="turn-1",
    )
    handler = HookHandler(app_paths, reviewer=lambda _input, _deadline: plan)
    assert handler.precompact(_hook_input()).continue_ is False
    plan_path = next(app_paths.plans_dir.glob("trim-*.json"))
    plan_path.write_bytes(b"{}")

    cached = handler.precompact(_hook_input())

    assert cached.continue_ is True
    key = HookInput.model_validate(_hook_input()).dedupe_key
    assert not handler.decisions.decision_path(key).exists()


def test_hook_decision_rejects_implausible_future_timestamp(app_paths) -> None:
    store = HookDecisionStore(app_paths)
    decision = HookDecision(
        key="future",
        session_id="session-1",
        turn_id="turn-1",
        trigger="auto",
        decided_at=utc_now() + timedelta(minutes=6),
        output=HookOutput.model_validate({"continue": True}),
    )
    store.save(decision)

    assert store.load(decision.key) is None
    assert not store.decision_path(decision.key).exists()


def test_hook_subprocess_stdout_is_exactly_one_json_object(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "CSM_DATA_DIR": str(tmp_path / "data"),
            "CSM_CONFIG_DIR": str(tmp_path / "config"),
            "CSM_CACHE_DIR": str(tmp_path / "cache"),
            "CSM_LOG_DIR": str(tmp_path / "log"),
            "CSM_CODEX_HOME": str(tmp_path / "codex"),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "codex_session_manager.dispatcher", "hook", "precompact"],
        input="{}",
        capture_output=True,
        text=True,
        env=environment,
        check=True,
        timeout=10,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    output = json.loads(lines[0])
    assert output["continue"] is True
    assert "suppressOutput" not in output


def test_hook_installer_merges_and_removes_only_csm_entries(
    tmp_path: Path, app_paths, monkeypatch
) -> None:
    executable = tmp_path / "CodexSessionManager"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr("codex_session_manager.hooks.stable_app_executable", lambda: executable)
    app_paths.codex_home.mkdir(parents=True)
    hooks_path = app_paths.codex_home / "hooks.json"
    custom = {
        "description": "custom",
        "hooks": {
            "PreCompact": [
                {
                    "matcher": "manual",
                    "hooks": [{"type": "command", "command": "/custom/hook"}],
                }
            ]
        },
    }
    hooks_path.write_text(json.dumps(custom), encoding="utf-8")
    installer = HookInstaller(app_paths)
    installer.install()
    assert installer.status()["ready"] is True
    installed = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert installed["hooks"]["PreCompact"][0] == custom["hooks"]["PreCompact"][0]
    installer.uninstall()
    removed = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert removed["hooks"]["PreCompact"] == custom["hooks"]["PreCompact"]
    assert "PostCompact" not in removed["hooks"]
