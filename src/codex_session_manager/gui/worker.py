"""Small typed QRunnable wrapper for non-blocking business operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    progress = Signal(object)
    error = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any], owner: QObject | None = None) -> None:
        super().__init__()
        self.function = function
        # QRunnable instances with auto-delete are destroyed by QThreadPool on
        # the worker thread.  Keeping the signal object parented to the GUI
        # controller prevents QObject wrappers (and their dynamic PySide slots)
        # from being torn down on that thread while a queued callback is still
        # being delivered.
        self.signals = WorkerSignals(owner)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            value = self.function()
        except BaseException as exc:
            self._emit(self.signals.error, str(exc))
        else:
            self._emit(self.signals.result, value)
        finally:
            self._emit(self.signals.finished)

    @staticmethod
    def _emit(signal: Any, *args: Any) -> None:
        """Ignore a callback after the Qt application has begun tearing down."""

        try:
            signal.emit(*args)
        except RuntimeError:
            # A parented WorkerSignals object can be deleted by Qt while a
            # request is still unwinding.  The window is already closing, so
            # there is no receiver left that can use this notification.
            return
