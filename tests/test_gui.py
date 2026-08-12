from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from codex_session_manager.gui.controller import ReviewDocument, TrimReviewWindow
from codex_session_manager.models import TrimAction, TrimPlan, TrimSelection


def _document(snapshot, capabilities) -> ReviewDocument:
    selection = TrimSelection(
        target_id=snapshot.turns[0].id,
        action=TrimAction.KEEP,
        suggested=True,
    )
    plan = TrimPlan.create(
        source_thread=snapshot,
        capability_fingerprint=capabilities.fingerprint,
        selections=(selection,),
        estimated_tokens_after=snapshot.token_estimate,
    )
    return ReviewDocument(snapshot, capabilities, plan)


def test_review_window_layout_and_stale_worker_result(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    window = TrimReviewWindow(paths=app_paths)
    qtbot.addWidget(window)
    assert window.minimumWidth() == 960
    assert window.minimumHeight() == 640
    assert window.width() == 1280
    assert window.height() == 800

    stale = _document(snapshot_factory("stale"), capabilities)
    window._document_loaded(99, stale)
    assert window.document is None

    current = _document(snapshot_factory("current"), capabilities)
    window._document_loaded(0, current)
    assert window.document == current
    assert window.ui.timelineView.model().rowCount() == 1
    assert window.ui.savePlanButton.isEnabled()
    assert window.ui.tokenLabel.text().startswith("预计上下文")


def test_protected_gui_target_refuses_exclusion(
    qtbot, app_paths, capabilities, snapshot_factory
) -> None:
    snapshot = snapshot_factory("protected")
    item = (
        snapshot.turns[0]
        .items[0]
        .model_copy(
            update={
                "hard_protected": True,
                "protected_reasons": ("current user request",),
            }
        )
    )
    snapshot = snapshot.model_copy(
        update={"turns": (snapshot.turns[0].model_copy(update={"items": (item,)}),)}
    )
    document = _document(snapshot, capabilities)
    window = TrimReviewWindow(paths=app_paths)
    qtbot.addWidget(window)
    window._document_loaded(0, document)
    window.current_target = snapshot.turns[0]
    window._show_target(snapshot.turns[0])
    window._action_changed(1)
    assert window.selections[snapshot.turns[0].id].action is TrimAction.KEEP
    assert "硬保护" in window.ui.errorLabel.text()


def test_designer_generated_modules_are_reproducible(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    pairs = (
        (
            root / "src/codex_session_manager/gui/main_window.ui",
            root / "src/codex_session_manager/gui/ui_main_window.py",
        ),
        (
            root / "src/codex_session_manager/gui/precompact_prompt.ui",
            root / "src/codex_session_manager/gui/ui_precompact_prompt.py",
        ),
    )
    for source, committed in pairs:
        generated = tmp_path / committed.name
        subprocess.run(
            [str(Path(sys.executable).with_name("pyside6-uic")), str(source), "-o", str(generated)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert generated.read_bytes() == committed.read_bytes()
