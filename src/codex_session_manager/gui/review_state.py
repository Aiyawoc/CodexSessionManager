"""Pure review-state transitions shared independently of Qt widgets."""

from __future__ import annotations

from dataclasses import dataclass

from codex_session_manager.models import (
    ThreadItemSnapshot,
    ThreadSnapshot,
    TrimAction,
    TrimSelection,
    TurnSnapshot,
)

ReviewTarget = TurnSnapshot | ThreadItemSnapshot


@dataclass(slots=True)
class ReviewState:
    snapshot: ThreadSnapshot
    selections: dict[str, TrimSelection]

    @classmethod
    def from_selections(
        cls,
        snapshot: ThreadSnapshot,
        selections: tuple[TrimSelection, ...],
    ) -> ReviewState:
        return cls(snapshot, {selection.target_id: selection for selection in selections})

    def estimated_tokens_after(self) -> int:
        total = 0
        for turn in self.snapshot.turns:
            selection = self.selections.get(turn.id)
            if selection and selection.action is TrimAction.EXCLUDE:
                continue
            if selection and selection.action is TrimAction.SUMMARY:
                total += _summary_tokens(selection.summary)
                continue
            for item in turn.items:
                item_selection = self.selections.get(item.id)
                if item_selection and item_selection.action is TrimAction.EXCLUDE:
                    continue
                if item_selection and item_selection.action is TrimAction.SUMMARY:
                    total += _summary_tokens(item_selection.summary)
                else:
                    total += item.token_estimate
        return total

    def normalize_selection_scope(self, target: ReviewTarget, *, keep_reason: str) -> None:
        """Make turn- and item-level actions mutually unambiguous."""

        if isinstance(target, TurnSnapshot):
            for item in target.items:
                self.selections.pop(item.id, None)
            return
        parent = next(
            (
                turn
                for turn in self.snapshot.turns
                if any(item.id == target.id for item in turn.items)
            ),
            None,
        )
        if parent is None:
            return
        parent_selection = self.selections.get(parent.id)
        if parent_selection is None or parent_selection.action is TrimAction.KEEP:
            return
        self.selections[parent.id] = TrimSelection(
            target_id=parent.id,
            target_level="turn",
            action=TrimAction.KEEP,
            reason=keep_reason,
            suggested=False,
        )


def protected_reasons(target: ReviewTarget) -> tuple[str, ...]:
    if isinstance(target, TurnSnapshot):
        return tuple(
            dict.fromkeys(reason for item in target.items for reason in item.protected_reasons)
        )
    return target.protected_reasons


def target_text(target: ReviewTarget) -> str:
    if isinstance(target, TurnSnapshot):
        return "\n".join(item.text for item in target.items if item.text)
    return target.text


def _summary_tokens(summary: str | None) -> int:
    return max(1, len((summary or "").encode("utf-8")) // 3)
