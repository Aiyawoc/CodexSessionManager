"""Adapters that turn untrusted external suggestions into local review state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from codex_session_manager.hashing import estimate_tokens
from codex_session_manager.models import (
    ThreadItemSnapshot,
    ThreadSnapshot,
    TrimAction,
    TrimPlan,
    TrimSelection,
    TurnSnapshot,
)
from codex_session_manager.review_requests import (
    ReviewOperation,
    SuggestedAction,
    SuggestionBundle,
)
from codex_session_manager.trim import TrimError, validate_selections

_ACTION_MAP: dict[SuggestedAction, TrimAction] = {
    SuggestedAction.KEEP: TrimAction.KEEP,
    SuggestedAction.EXCLUDE: TrimAction.EXCLUDE,
    SuggestedAction.SUMMARY: TrimAction.SUMMARY,
    SuggestedAction.PROTECT: TrimAction.PROTECT,
}


@dataclass(frozen=True, slots=True)
class ExternalSuggestionResult:
    """A locally rebuilt TrimPlan plus suggestions rejected by hard protection."""

    plan: TrimPlan
    applied_target_ids: tuple[str, ...]
    ignored_protected_target_ids: tuple[str, ...]


def _protected_reasons(target: TurnSnapshot | ThreadItemSnapshot) -> tuple[str, ...]:
    if isinstance(target, TurnSnapshot):
        return tuple(
            dict.fromkeys(
                reason
                for item in target.items
                if item.hard_protected
                for reason in item.protected_reasons
            )
        )
    return target.protected_reasons if target.hard_protected else ()


def _tokens_after(
    snapshot: ThreadSnapshot,
    selections: dict[str, TrimSelection],
) -> int:
    total = 0
    for turn in snapshot.turns:
        turn_selection = selections.get(turn.id)
        if turn_selection is not None:
            if turn_selection.action is TrimAction.EXCLUDE:
                continue
            if turn_selection.action is TrimAction.SUMMARY:
                total += estimate_tokens(turn_selection.summary or "")
                continue
        for item in turn.items:
            item_selection = selections.get(item.id)
            if item_selection is None or item_selection.action in {
                TrimAction.KEEP,
                TrimAction.PROTECT,
            }:
                total += item.token_estimate
            elif item_selection.action is TrimAction.SUMMARY:
                total += estimate_tokens(item_selection.summary or "")
    return total


class ExternalSuggestionBundleProvider:
    """Overlay a sealed context suggestion bundle on deterministic local defaults.

    The provider never trusts external target identity, content fingerprints, or
    hard-protection decisions.  It rebuilds a fresh TrimPlan from the current
    App Server snapshot and leaves ``validate_selections`` with final veto power.
    """

    def apply(
        self,
        *,
        snapshot: ThreadSnapshot,
        base_plan: TrimPlan,
        bundle: SuggestionBundle,
    ) -> ExternalSuggestionResult:
        bundle.verify()
        base_plan.verify()
        if bundle.operation is not ReviewOperation.CONTEXT_TRIM:
            raise ValueError("external trim provider requires a context_trim bundle")
        if base_plan.source_thread_id != snapshot.id:
            raise ValueError("base trim plan belongs to another conversation")
        if base_plan.source_thread_fingerprint != snapshot.trim_fingerprint:
            raise ValueError("base trim plan no longer matches the conversation")

        turns = {turn.id: turn for turn in snapshot.turns}
        items = {item.id: item for turn in snapshot.turns for item in turn.items}
        item_parents = {item.id: turn for turn in snapshot.turns for item in turn.items}
        selections = {selection.target_id: selection for selection in base_plan.selections}
        applied: list[str] = []
        ignored: list[str] = []

        for suggestion in bundle.targets:
            if suggestion.target_id is None:
                raise ValueError("context suggestion must target a turn or item id")
            target: TurnSnapshot | ThreadItemSnapshot | None = turns.get(suggestion.target_id)
            target_level: Literal["turn", "item"] = "turn"
            if target is None:
                target = items.get(suggestion.target_id)
                target_level = "item"
            if target is None:
                raise ValueError(
                    f"external suggestion references an unknown target: {suggestion.target_id}"
                )
            if suggestion.source_fingerprint != target.content_fingerprint:
                raise ValueError(
                    f"external suggestion fingerprint changed for target: {suggestion.target_id}"
                )
            action = _ACTION_MAP.get(suggestion.suggested_action)
            if action is None:
                raise ValueError(
                    f"unsupported context suggestion action: {suggestion.suggested_action.value}"
                )

            protected = _protected_reasons(target)
            if protected and action not in {TrimAction.KEEP, TrimAction.PROTECT}:
                ignored.append(suggestion.target_id)
                continue
            if protected:
                action = TrimAction.PROTECT

            if isinstance(target, TurnSnapshot):
                for item in target.items:
                    selections.pop(item.id, None)
            else:
                parent = item_parents[target.id]
                parent_selection = selections.get(parent.id)
                if parent_selection is not None and parent_selection.action is not TrimAction.KEEP:
                    selections[parent.id] = TrimSelection(
                        target_id=parent.id,
                        target_level="turn",
                        action=TrimAction.KEEP,
                        reason="外部 item 建议要求保留父 turn 并进入 item 级复核",
                        suggested=False,
                    )

            selections[suggestion.target_id] = TrimSelection(
                target_id=suggestion.target_id,
                target_level=target_level,
                action=action,
                summary=suggestion.suggested_text if action is TrimAction.SUMMARY else None,
                reason=suggestion.reason,
                suggested=True,
                confidence=suggestion.confidence,
                protected_reasons=protected if action is TrimAction.PROTECT else (),
            )
            applied.append(suggestion.target_id)

        rebuilt = tuple(selections.values())
        try:
            validate_selections(snapshot, rebuilt)
        except TrimError as exc:
            raise ValueError(f"external suggestions failed local safety validation: {exc}") from exc
        plan = TrimPlan.create(
            source_thread=snapshot,
            capability_fingerprint=base_plan.capability_fingerprint,
            selections=rebuilt,
            estimated_tokens_after=_tokens_after(snapshot, selections),
            trigger=base_plan.trigger,
            source_turn_id=base_plan.source_turn_id,
        )
        return ExternalSuggestionResult(plan, tuple(applied), tuple(ignored))
