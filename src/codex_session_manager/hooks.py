"""Codex PreCompact/PostCompact hook protocol and safe installation."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import shlex
import shutil
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from codex_session_manager.config import AppPaths, private_atomic_write, stable_app_executable
from codex_session_manager.hashing import canonical_json_bytes, fingerprint, utc_now
from codex_session_manager.models import TrimPlan
from codex_session_manager.plans import PlanStore

LOGGER = logging.getLogger(__name__)
HOOK_TIMEOUT_SECONDS = 600
INTERNAL_DEADLINE_SECONDS = 540
LIGHT_PROMPT_SECONDS = 15
MAX_HOOK_INPUT_BYTES = 1024 * 1024
CSM_STATUS_PREFIX = "CSM 上下文裁剪"


class HookInput(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    session_id: str = Field(min_length=1)
    transcript_path: str | None
    cwd: str
    hook_event_name: str
    model: str
    turn_id: str = Field(min_length=1)
    trigger: Literal["manual", "auto"]

    @property
    def dedupe_key(self) -> str:
        return fingerprint(
            {
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "trigger": self.trigger,
            }
        )


class HookOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    continue_: bool = Field(alias="continue")
    stopReason: str | None = None
    systemMessage: str | None = None


class HookDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    session_id: str
    turn_id: str
    trigger: Literal["manual", "auto"]
    decided_at: datetime
    output: HookOutput
    plan_path: str | None = None
    plan_sha256: str | None = None
    capability_fingerprint: str | None = None


Reviewer = Callable[[HookInput, float], TrimPlan | None]


def _continue(message: str | None = None) -> HookOutput:
    return HookOutput.model_validate({"continue": True, "systemMessage": message})


def _stop(plan: TrimPlan) -> HookOutput:
    return HookOutput.model_validate(
        {
            "continue": False,
            "stopReason": "CSM TrimPlan 已保存；本次原生压缩已停止。请在任务 idle 后应用计划。",
            "systemMessage": f"CSM 已保存上下文裁剪计划 {plan.plan_id}，原任务保持不变。",
        }
    )


class HookDecisionStore:
    def __init__(self, paths: AppPaths) -> None:
        self.root = paths.data_dir / "hook-decisions"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_path = self.root / ".lock"

    def decision_path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    @contextlib.contextmanager
    def try_lock(self) -> Any:
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(descriptor, "r+")
        try:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stream.close()
                yield None
                return
            try:
                yield stream
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()
        except BaseException:
            if not stream.closed:
                stream.close()
            raise

    def load(self, key: str, *, maximum_age: timedelta = timedelta(hours=1)) -> HookDecision | None:
        path = self.decision_path(key)
        if not path.is_file():
            return None
        decision = HookDecision.model_validate_json(path.read_bytes())
        age = utc_now() - decision.decided_at.astimezone(UTC)
        if age < -timedelta(minutes=5) or age > maximum_age:
            path.unlink(missing_ok=True)
            return None
        return decision

    def discard(self, key: str) -> None:
        self.decision_path(key).unlink(missing_ok=True)

    def save(self, decision: HookDecision) -> Path:
        path = self.decision_path(decision.key)
        private_atomic_write(path, canonical_json_bytes(decision))
        return path

    def prune(self, *, maximum_age: timedelta = timedelta(days=1)) -> int:
        removed = 0
        cutoff = utc_now() - maximum_age
        for path in self.root.glob("*.json"):
            try:
                decision = HookDecision.model_validate_json(path.read_bytes())
            except (OSError, ValueError):
                continue
            if decision.decided_at.astimezone(UTC) < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


class HookHandler:
    def __init__(self, paths: AppPaths, reviewer: Reviewer | None = None) -> None:
        self.paths = paths
        self.reviewer = reviewer or self._default_reviewer
        self.decisions = HookDecisionStore(paths)
        self.plans = PlanStore(paths)

    @staticmethod
    def _default_reviewer(hook_input: HookInput, deadline: float) -> TrimPlan | None:
        from codex_session_manager.gui.prompt import review_precompact

        return review_precompact(
            thread_id=hook_input.session_id,
            turn_id=hook_input.turn_id,
            trigger=hook_input.trigger,
            cwd=hook_input.cwd,
            prompt_seconds=LIGHT_PROMPT_SECONDS,
            deadline=deadline,
        )

    def precompact(self, raw: Mapping[str, Any]) -> HookOutput:
        hook_input = HookInput.model_validate(raw)
        if hook_input.hook_event_name != "PreCompact":
            return _continue("CSM hook event mismatch; native compaction continued.")
        deadline = time.monotonic() + INTERNAL_DEADLINE_SECONDS
        with self.decisions.try_lock() as lock:
            if lock is None:
                return _continue("CSM review is already running; native compaction continued.")
            try:
                existing = self.decisions.load(hook_input.dedupe_key)
                if existing:
                    self._validate_cached_decision(existing, hook_input)
                    return existing.output
            except BaseException:
                self.decisions.discard(hook_input.dedupe_key)
                LOGGER.exception("cached Hook decision was invalid; continuing native compaction")
                return _continue("CSM cached review was invalid; native compaction continued.")
            try:
                plan = self.reviewer(hook_input, deadline)
                if plan is None or time.monotonic() >= deadline:
                    output = _continue()
                    plan_path = None
                else:
                    plan.verify()
                    if (
                        plan.source_thread_id != hook_input.session_id
                        or plan.source_turn_id != hook_input.turn_id
                        or plan.trigger != "hook"
                    ):
                        raise ValueError("reviewer returned a TrimPlan bound to another Hook event")
                    # The persisted plan is the only condition under which the
                    # hook may stop native compaction.
                    persisted = self.plans.save(plan)
                    output = _stop(plan)
                    plan_path = str(persisted)
            except BaseException:
                LOGGER.exception("PreCompact review failed; continuing native compaction")
                output = _continue("CSM review failed; native compaction continued.")
                plan_path = None
            self.decisions.save(
                HookDecision(
                    key=hook_input.dedupe_key,
                    session_id=hook_input.session_id,
                    turn_id=hook_input.turn_id,
                    trigger=hook_input.trigger,
                    decided_at=utc_now(),
                    output=output,
                    plan_path=plan_path,
                    plan_sha256=(plan.plan_sha256 if plan_path and plan is not None else None),
                    capability_fingerprint=(
                        plan.capability_fingerprint if plan_path and plan is not None else None
                    ),
                )
            )
            return output

    def _validate_cached_decision(self, decision: HookDecision, hook_input: HookInput) -> None:
        if (
            decision.key != hook_input.dedupe_key
            or decision.session_id != hook_input.session_id
            or decision.turn_id != hook_input.turn_id
            or decision.trigger != hook_input.trigger
        ):
            raise ValueError("cached Hook decision binding mismatch")
        if decision.output.continue_:
            if any(
                value is not None
                for value in (
                    decision.plan_path,
                    decision.plan_sha256,
                    decision.capability_fingerprint,
                )
            ):
                raise ValueError("continue decision unexpectedly references a TrimPlan")
            return
        if not all(
            (
                decision.plan_path,
                decision.plan_sha256,
                decision.capability_fingerprint,
            )
        ):
            raise ValueError("blocking decision lacks a complete TrimPlan binding")
        plan_path = Path(decision.plan_path or "")
        resolved = plan_path.resolve(strict=True)
        plans_root = self.paths.plans_dir.resolve(strict=False)
        if plan_path.is_symlink() or resolved.parent != plans_root:
            raise ValueError("cached Hook plan path escaped the private plans directory")
        plan = self.plans.load_trim(resolved)
        if resolved != self.plans.path_for(plan).resolve(strict=False):
            raise ValueError("cached Hook plan path does not match its sealed identity")
        if (
            plan.plan_sha256 != decision.plan_sha256
            or plan.capability_fingerprint != decision.capability_fingerprint
            or plan.source_thread_id != hook_input.session_id
            or plan.source_turn_id != hook_input.turn_id
            or plan.trigger != "hook"
        ):
            raise ValueError("cached Hook TrimPlan binding mismatch")

    def postcompact(self, raw: Mapping[str, Any]) -> HookOutput:
        hook_input = HookInput.model_validate(raw)
        if hook_input.hook_event_name != "PostCompact":
            return _continue()
        self.decisions.prune()
        return _continue()


def _handler_command(mode: str) -> str:
    executable = stable_app_executable()
    return shlex.join([str(executable), "hook", mode])


def _is_csm_handler(handler: Any, mode: str) -> bool:
    if not isinstance(handler, Mapping):
        return False
    return handler.get("type") == "command" and handler.get("command") == _handler_command(mode)


class HookInstaller:
    """Merge only CSM-owned entries into the user-level hooks.json."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.path = paths.codex_home / "hooks.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"description": "User-level Codex hooks", "hooks": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("hooks", {}), dict):
            raise ValueError(f"unsupported hooks.json structure: {self.path}")
        value.setdefault("hooks", {})
        return value

    def _backup(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        destination = self.path.with_name(f"hooks.json.before-csm-{stamp}")
        shutil.copy2(self.path, destination)
        return destination

    def status(self) -> dict[str, Any]:
        config = self._load()
        hooks = config["hooks"]
        result: dict[str, Any] = {"path": str(self.path), "app": str(stable_app_executable())}
        for event, mode in (("PreCompact", "precompact"), ("PostCompact", "postcompact")):
            groups = hooks.get(event, [])
            installed = False
            if isinstance(groups, list):
                for group in groups:
                    handlers = group.get("hooks", []) if isinstance(group, Mapping) else []
                    if any(_is_csm_handler(handler, mode) for handler in handlers):
                        installed = True
            result[event] = installed
        result["ready"] = all(result[event] for event in ("PreCompact", "PostCompact"))
        return result

    def install(self) -> Path:
        executable = stable_app_executable()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise FileNotFoundError(
                f"stable app executable is missing: {executable}; install the .app before hooks"
            )
        config = self._load()
        hooks = config["hooks"]
        for event, mode, timeout, message in (
            ("PreCompact", "precompact", HOOK_TIMEOUT_SECONDS, f"{CSM_STATUS_PREFIX}审查"),
            ("PostCompact", "postcompact", 30, f"{CSM_STATUS_PREFIX}收尾"),
        ):
            groups = hooks.setdefault(event, [])
            if not isinstance(groups, list):
                raise ValueError(f"hooks.{event} must be an array")
            already = any(
                _is_csm_handler(handler, mode)
                for group in groups
                if isinstance(group, Mapping)
                for handler in group.get("hooks", [])
            )
            if not already:
                groups.append(
                    {
                        "matcher": "manual|auto",
                        "hooks": [
                            {
                                "type": "command",
                                "command": _handler_command(mode),
                                "timeout": timeout,
                                "statusMessage": message,
                            }
                        ],
                    }
                )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._backup()
        private_atomic_write(
            self.path, json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        )
        return self.path

    def uninstall(self) -> Path:
        config = self._load()
        hooks = config["hooks"]
        for event, mode in (("PreCompact", "precompact"), ("PostCompact", "postcompact")):
            groups = hooks.get(event, [])
            if not isinstance(groups, list):
                continue
            retained_groups: list[Any] = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    retained_groups.append(group)
                    continue
                retained_handlers = [
                    handler for handler in group["hooks"] if not _is_csm_handler(handler, mode)
                ]
                if retained_handlers:
                    group = dict(group)
                    group["hooks"] = retained_handlers
                    retained_groups.append(group)
            if retained_groups:
                hooks[event] = retained_groups
            else:
                hooks.pop(event, None)
        self._backup()
        private_atomic_write(
            self.path, json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        )
        return self.path


def configure_hook_logging(paths: AppPaths) -> None:
    paths.ensure()
    log_path = paths.log_dir / "hooks.log"
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.close(descriptor)
    log_path.chmod(0o600)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def run_hook(mode: Literal["precompact", "postcompact"], paths: AppPaths) -> int:
    """Read one hook JSON object and emit exactly one final JSON object."""

    try:
        configure_hook_logging(paths)
    except OSError:
        # A read-only or damaged application data directory must never prevent
        # the fail-open Hook response from reaching Codex.
        logging.basicConfig(handlers=[logging.NullHandler()], force=True)
    output = _continue("CSM hook failed before startup; native compaction continued.")
    saved_stdout: int | None = None
    try:
        stdout_fd = sys.stdout.fileno()
        saved_stdout = os.dup(stdout_fd)
        sys.stdout.flush()
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), stdout_fd)
            try:
                raw_bytes = sys.stdin.buffer.read(MAX_HOOK_INPUT_BYTES + 1)
                if len(raw_bytes) > MAX_HOOK_INPUT_BYTES:
                    raise ValueError("hook input exceeds 1 MiB")
                raw = json.loads(raw_bytes)
                if not isinstance(raw, Mapping):
                    raise ValueError("hook input must be an object")
                handler = HookHandler(paths)
                output = (
                    handler.precompact(raw) if mode == "precompact" else handler.postcompact(raw)
                )
            except BaseException:
                LOGGER.exception("hook entrypoint failed; fail-open")
                output = _continue("CSM hook failed; native compaction continued.")
            sys.stdout.flush()
    except BaseException:
        LOGGER.exception("hook stdout isolation failed; fail-open")
    finally:
        if saved_stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                os.dup2(saved_stdout, sys.stdout.fileno())
            with contextlib.suppress(OSError):
                os.close(saved_stdout)
    encoded = (output.model_dump_json(by_alias=True, exclude_none=True) + "\n").encode()
    try:
        sys.stdout.write(encoded.decode())
        sys.stdout.flush()
    except BaseException:
        os.write(1, encoded)
    return 0
