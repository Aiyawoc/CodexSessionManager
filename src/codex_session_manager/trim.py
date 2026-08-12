"""Context-trimming suggestions, projection generation, and derived-thread apply."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Literal, Protocol, cast
from uuid import uuid4

from codex_session_manager.app_server import SubprocessAppServer
from codex_session_manager.audit import AuditStore
from codex_session_manager.hashing import estimate_tokens, fingerprint, utc_now
from codex_session_manager.inventory import InventoryService, model_visible_messages
from codex_session_manager.models import (
    CapabilityMatrix,
    ContextProjection,
    ItemKind,
    ProjectionEntry,
    ThreadItemSnapshot,
    ThreadSnapshot,
    ThreadStatus,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)

UNRESOLVED_ERROR_PATTERN = re.compile(
    r"\b(unresolved|still failing|not fixed|blocked|traceback|exception|fatal|error)\b|未解决|仍失败|阻塞|异常|错误",
    re.IGNORECASE,
)
LOW_INFORMATION_PATTERN = re.compile(
    r"^(ok|okay|thanks|thank you|yes|no|好的|收到|谢谢|可以|继续|嗯)[.!。！\s]*$",
    re.IGNORECASE,
)


class TrimError(RuntimeError):
    pass


class ContentSuggestionProvider(Protocol):
    """Opt-in provider; implementations must not run unless the user consents."""

    def suggest(self, snapshot: ThreadSnapshot) -> tuple[TrimSelection, ...]: ...


def _turn_text(turn: TurnSnapshot) -> str:
    return "\n".join(item.text for item in turn.items if item.text)


def _turn_tokens(turn: TurnSnapshot) -> int:
    return sum(item.token_estimate for item in turn.items)


def _summary_text(turn: TurnSnapshot, *, maximum_chars: int = 1200) -> str:
    lines = [line.strip() for line in _turn_text(turn).splitlines() if line.strip()]
    if not lines:
        return f"Turn {turn.id}: no model-visible text; metadata retained in the manifest."
    if len("\n".join(lines)) <= maximum_chars:
        return "\n".join(lines)
    head = lines[:6]
    tail = lines[-4:] if len(lines) > 6 else []
    summary = "\n".join((*head, "… [middle omitted by local deterministic summary] …", *tail))
    return summary[:maximum_chars]


def _turn_atomic_groups(turn: TurnSnapshot) -> tuple[frozenset[str], ...]:
    groups: dict[str, set[str]] = defaultdict(set)
    for item in turn.items:
        call_id = item.metadata.get("call_id")
        if isinstance(call_id, str):
            groups[f"call:{call_id}"].add(item.id)
        for dependency in item.depends_on:
            key = ":".join(sorted((item.id, dependency)))
            groups[f"dependency:{key}"].update((item.id, dependency))
        if item.kind is ItemKind.FILE_CHANGE:
            groups[f"file-change-turn:{turn.id}"].update(child.id for child in turn.items)
    return tuple(frozenset(group) for group in groups.values() if len(group) > 1)


def validate_selections(snapshot: ThreadSnapshot, selections: tuple[TrimSelection, ...]) -> None:
    turns = {turn.id: turn for turn in snapshot.turns}
    items = {item.id: item for turn in snapshot.turns for item in turn.items}
    selection_by_id = {selection.target_id: selection for selection in selections}
    if len(selection_by_id) != len(selections):
        raise TrimError("duplicate trim selection target")
    for selection in selections:
        if selection.target_level == "turn":
            turn = turns.get(selection.target_id)
            if turn is None:
                raise TrimError(f"unknown turn selection: {selection.target_id}")
            protected = [item for item in turn.items if item.hard_protected]
            if protected and selection.action not in {TrimAction.KEEP, TrimAction.PROTECT}:
                raise TrimError(f"turn {turn.id} contains hard-protected items")
        else:
            item = items.get(selection.target_id)
            if item is None:
                raise TrimError(f"unknown item selection: {selection.target_id}")
            if item.hard_protected and selection.action not in {
                TrimAction.KEEP,
                TrimAction.PROTECT,
            }:
                raise TrimError(f"item {item.id} is hard-protected")
    for turn in snapshot.turns:
        item_actions: dict[str, TrimAction] = {}
        turn_selection = selection_by_id.get(turn.id)
        item_selections = [
            selection_by_id[item.id] for item in turn.items if item.id in selection_by_id
        ]
        if (
            turn_selection is not None
            and turn_selection.action is not TrimAction.KEEP
            and item_selections
        ):
            raise TrimError(f"turn {turn.id} uses a non-keep action together with item overrides")
        for item in turn.items:
            item_selection = selection_by_id.get(item.id)
            action = (
                item_selection.action
                if item_selection
                else (turn_selection.action if turn_selection else TrimAction.KEEP)
            )
            item_actions[item.id] = action
        for group in _turn_atomic_groups(turn):
            actions = {item_actions[item_id] for item_id in group if item_id in item_actions}
            normalized = {
                TrimAction.KEEP if action is TrimAction.PROTECT else action for action in actions
            }
            if len(normalized) > 1:
                raise TrimError(
                    f"atomic tool/file group in turn {turn.id} must use one action together"
                )
            if normalized == {TrimAction.EXCLUDE}:
                raise TrimError(
                    f"atomic tool/file group in turn {turn.id} may be kept or summarized, not excluded"
                )


class LocalTrimSuggester:
    """Deterministic local rules; no conversation content leaves the machine."""

    def __init__(self, *, keep_recent_turns: int = 2, long_turn_tokens: int = 2500) -> None:
        self.keep_recent_turns = keep_recent_turns
        self.long_turn_tokens = long_turn_tokens

    def suggest(
        self,
        snapshot: ThreadSnapshot,
        *,
        capabilities: CapabilityMatrix,
        trigger: str = "manual",
        source_turn_id: str | None = None,
        content_ai: ContentSuggestionProvider | None = None,
        allow_content_ai: bool = False,
    ) -> TrimPlan:
        if allow_content_ai:
            if content_ai is None:
                raise TrimError("content AI was allowed but no explicit provider was configured")
            ai_selections = content_ai.suggest(snapshot)
            validate_selections(snapshot, ai_selections)
            return self._plan(snapshot, capabilities, ai_selections, trigger, source_turn_id)
        seen_turn_hashes: dict[str, int] = {}
        turn_hashes = [fingerprint(_turn_text(turn).strip()) for turn in snapshot.turns]
        for index, value in enumerate(turn_hashes):
            seen_turn_hashes[value] = index
        local_selections: list[TrimSelection] = []
        recent_start = max(0, len(snapshot.turns) - self.keep_recent_turns)
        for index, turn in enumerate(snapshot.turns):
            text = _turn_text(turn).strip()
            tokens = _turn_tokens(turn)
            protected_reasons = tuple(
                dict.fromkeys(
                    reason
                    for item in turn.items
                    if item.hard_protected
                    for reason in item.protected_reasons
                )
            )
            if protected_reasons:
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.PROTECT,
                    reason="硬保护项所在 turn",
                    suggested=True,
                    confidence=1.0,
                    protected_reasons=protected_reasons,
                )
            elif index >= recent_start:
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.KEEP,
                    reason="保留最近 turn",
                    suggested=True,
                    confidence=0.98,
                )
            elif UNRESOLVED_ERROR_PATTERN.search(text):
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.PROTECT,
                    reason="可能包含未解决错误，需人工确认",
                    suggested=True,
                    confidence=0.75,
                    protected_reasons=("possible unresolved error",),
                )
            elif text and seen_turn_hashes.get(turn_hashes[index], index) > index:
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.EXCLUDE,
                    reason="后续 turn 已包含完全相同内容",
                    suggested=True,
                    confidence=0.99,
                )
            elif LOW_INFORMATION_PATTERN.match(text):
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.EXCLUDE,
                    reason="低信息确认语",
                    suggested=True,
                    confidence=0.9,
                )
            elif tokens >= self.long_turn_tokens or any(
                item.kind in {ItemKind.TOOL_CALL, ItemKind.TOOL_RESULT, ItemKind.FILE_CHANGE}
                for item in turn.items
            ):
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.SUMMARY,
                    summary=_summary_text(turn),
                    reason="长输出或工具链建议整体摘要",
                    suggested=True,
                    confidence=0.78,
                )
            else:
                selection = TrimSelection(
                    target_id=turn.id,
                    action=TrimAction.KEEP,
                    reason="没有足够证据安全裁剪",
                    suggested=True,
                    confidence=0.65,
                )
            local_selections.append(selection)
        return self._plan(
            snapshot,
            capabilities,
            tuple(local_selections),
            trigger,
            source_turn_id,
        )

    @staticmethod
    def _plan(
        snapshot: ThreadSnapshot,
        capabilities: CapabilityMatrix,
        selections: tuple[TrimSelection, ...],
        trigger: str,
        source_turn_id: str | None,
    ) -> TrimPlan:
        validate_selections(snapshot, selections)
        actions = {selection.target_id: selection for selection in selections}
        tokens_after = 0
        for turn in snapshot.turns:
            selection = actions.get(turn.id)
            if selection is None or selection.action in {TrimAction.KEEP, TrimAction.PROTECT}:
                tokens_after += _turn_tokens(turn)
            elif selection.action is TrimAction.SUMMARY:
                tokens_after += estimate_tokens(selection.summary or "")
        trigger_value = cast(
            Literal["manual", "auto", "hook"],
            trigger if trigger in {"manual", "auto", "hook"} else "manual",
        )
        return TrimPlan.create(
            source_thread=snapshot,
            capability_fingerprint=capabilities.fingerprint,
            selections=selections,
            estimated_tokens_after=tokens_after,
            trigger=trigger_value,
            source_turn_id=source_turn_id,
        )


def _item_action(
    turn: TurnSnapshot,
    item: ThreadItemSnapshot,
    selections: Mapping[str, TrimSelection],
) -> tuple[TrimAction, str | None]:
    item_selection = selections.get(item.id)
    turn_selection = selections.get(turn.id)
    selection = item_selection or turn_selection
    if selection is None:
        return TrimAction.KEEP, None
    return selection.action, selection.summary


def build_projection(snapshot: ThreadSnapshot, plan: TrimPlan) -> ContextProjection:
    plan.verify()
    if plan.source_thread_id != snapshot.id:
        raise TrimError("TrimPlan source thread mismatch")
    if plan.source_thread_fingerprint != snapshot.trim_fingerprint:
        raise TrimError("source thread changed after trim planning")
    validate_selections(snapshot, plan.selections)
    selections = {selection.target_id: selection for selection in plan.selections}
    entries: list[ProjectionEntry] = []
    excluded: list[str] = []
    summarized_turns: set[str] = set()
    for turn in snapshot.turns:
        turn_selection = selections.get(turn.id)
        if turn_selection and turn_selection.action is TrimAction.SUMMARY:
            entries.append(
                ProjectionEntry(
                    source_id=turn.id,
                    action=TrimAction.SUMMARY,
                    text=turn_selection.summary or "",
                    source_fingerprint=turn.content_fingerprint,
                )
            )
            summarized_turns.add(turn.id)
            continue
        if turn_selection and turn_selection.action is TrimAction.EXCLUDE:
            excluded.extend(item.id for item in turn.items)
            continue
        for item in turn.items:
            action, summary = _item_action(turn, item, selections)
            if action is TrimAction.EXCLUDE:
                excluded.append(item.id)
                continue
            text = summary or item.text if action is TrimAction.SUMMARY else item.text
            if not text:
                continue
            # System and developer instructions are reloaded from the target
            # project. Their historical bodies are not injected as user-visible
            # messages; the manifest still records their fingerprints/actions.
            if item.kind in {ItemKind.SYSTEM_MESSAGE, ItemKind.DEVELOPER_MESSAGE}:
                continue
            entries.append(
                ProjectionEntry(
                    source_id=item.id,
                    action=action,
                    text=text,
                    source_fingerprint=item.content_fingerprint,
                )
            )
    manifest = {
        "projection": "CodexSessionManager ContextProjection",
        "source_thread_id": snapshot.id,
        "source_thread_fingerprint": snapshot.trim_fingerprint,
        "trim_plan_sha256": plan.plan_sha256,
        "instructions": "Current project system/developer instructions are reloaded; historical copies were not injected.",
        "entries": [
            {
                "source_id": entry.source_id,
                "action": entry.action.value,
                "source_fingerprint": entry.source_fingerprint,
            }
            for entry in entries
        ],
        "excluded_ids": excluded,
        "summarized_turns": sorted(summarized_turns),
    }
    projection = ContextProjection(
        projection_id=str(uuid4()),
        source_thread_id=snapshot.id,
        source_thread_fingerprint=snapshot.trim_fingerprint,
        trim_plan_sha256=plan.plan_sha256,
        created_at=utc_now(),
        entries=tuple(entries),
        excluded_ids=tuple(excluded),
        manifest_text=json.dumps(manifest, ensure_ascii=False, sort_keys=True),
    ).seal()
    return projection


def prefix_fork_turn(snapshot: ThreadSnapshot, plan: TrimPlan) -> str | None:
    """Return a cutoff turn only when retained history is one exact prefix."""

    selections = {selection.target_id: selection for selection in plan.selections}
    if any(selection.target_level == "item" for selection in plan.selections):
        return None
    retained: list[bool] = []
    for turn in snapshot.turns:
        action = selections.get(
            turn.id, TrimSelection(target_id=turn.id, action=TrimAction.KEEP)
        ).action
        if action is TrimAction.SUMMARY:
            return None
        retained.append(action in {TrimAction.KEEP, TrimAction.PROTECT})
    if not retained or not retained[0]:
        return None
    first_excluded = next(
        (index for index, value in enumerate(retained) if not value), len(retained)
    )
    if any(retained[first_excluded:]):
        return None
    cutoff = first_excluded - 1
    return snapshot.turns[cutoff].id if cutoff >= 0 else None


class TrimExecutor:
    """Create a derived thread; never modify or compact the source thread."""

    def __init__(
        self,
        *,
        client: SubprocessAppServer,
        inventory: InventoryService,
        capabilities: CapabilityMatrix,
        audit: AuditStore,
    ) -> None:
        self.client = client
        self.inventory = inventory
        self.capabilities = capabilities
        self.audit = audit

    def apply(self, plan: TrimPlan) -> str:
        plan.verify()
        if plan.capability_fingerprint != self.capabilities.fingerprint:
            raise TrimError("App Server capability drift invalidated the TrimPlan")
        source = self.inventory.read(plan.source_thread_id, include_turns=True)
        if source.trim_fingerprint != plan.source_thread_fingerprint:
            raise TrimError("source thread changed after TrimPlan creation")
        if source.status is not ThreadStatus.IDLE:
            raise TrimError("wait for the source thread to become idle before applying TrimPlan")
        validate_selections(source, plan.selections)
        cutoff = prefix_fork_turn(source, plan)
        self.audit.begin_operation(plan_sha256=plan.plan_sha256, action="trim")
        target_id: str | None = None
        prefix_strategy: str | None = None
        try:
            if cutoff:
                self.capabilities.require_write("thread/fork")
                cutoff_index = next(
                    index for index, turn in enumerate(source.turns) if turn.id == cutoff
                )
                if self.capabilities.fork_supports_last_turn_id:
                    target = self.client.fork_thread(source.id, last_turn_id=cutoff)
                    prefix_strategy = "fork-last-turn-id"
                else:
                    self.capabilities.require_write("thread/rollback")
                    target = self.client.fork_thread(source.id)
                    target_value = target.get("id")
                    if not isinstance(target_value, str):
                        raise TrimError("thread/fork returned no derived thread id")
                    turns_to_drop = len(source.turns) - cutoff_index - 1
                    if turns_to_drop:
                        self.client.rollback_thread(target_value, num_turns=turns_to_drop)
                        prefix_strategy = "fork-then-rollback-derived"
                    else:
                        prefix_strategy = "fork-full-history"
                target_value = target.get("id")
                if not isinstance(target_value, str):
                    raise TrimError("thread/fork returned no derived thread id")
                target_id = target_value
                derived = self.inventory.read(target_id, include_turns=True)
                expected_turn_ids = tuple(turn.id for turn in source.turns[: cutoff_index + 1])
                if tuple(turn.id for turn in derived.turns) != expected_turn_ids:
                    raise TrimError("derived prefix does not match the reviewed turn boundary")
            else:
                self.capabilities.require_write("thread/start")
                self.capabilities.require_write("thread/inject_items")
                self.capabilities.require_write("thread/name/set")
                projection = build_projection(source, plan)
                target = self.client.start_thread(
                    cwd=source.cwd,
                    name=(source.title or source.id) + " · 精简",
                )
                target_id = str(target["id"])
                text = (
                    "CSM ContextProjection\n"
                    f"projection_sha256={projection.projection_sha256}\n"
                    f"manifest={projection.manifest_text}\n\n"
                    + "\n\n".join(entry.text for entry in projection.entries)
                )
                self.client.inject_items(
                    target_id,
                    [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ],
                )
                reread = self.client.read_thread(target_id, include_turns=True)
                observed_messages = model_visible_messages(reread)
                if observed_messages[-1:] != (("assistant", text),):
                    raise TrimError(
                        "derived thread failed post-injection ordered-message verification"
                    )
            source_after = self.inventory.read(source.id, include_turns=True)
            if source_after.trim_fingerprint != source.trim_fingerprint:
                raise TrimError("source thread changed while creating the derived thread")
            self.audit.finish_operation(plan_sha256=plan.plan_sha256, status="succeeded")
            self.audit.append(
                event_type="trim.apply",
                actor="human",
                result="succeeded",
                plan_sha256=plan.plan_sha256,
                target_ids=(source.id, target_id),
                details={
                    "source_preserved": True,
                    "prefix_fork": bool(cutoff),
                    "prefix_strategy": prefix_strategy,
                },
            )
            return target_id
        except BaseException as exc:
            self.audit.finish_operation(
                plan_sha256=plan.plan_sha256, status="failed", error=str(exc)
            )
            self.audit.append(
                event_type="trim.apply",
                actor="human",
                result="failed",
                plan_sha256=plan.plan_sha256,
                target_ids=tuple(value for value in (source.id, target_id) if value),
                details={"error": str(exc), "source_preserved": True},
            )
            raise
