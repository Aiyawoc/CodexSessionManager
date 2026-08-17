"""Shared GUI review modes."""

from __future__ import annotations

from enum import StrEnum


class ReviewMode(StrEnum):
    CONTEXT_TRIM = "context_trim"
    CONVERSATION_CLEANUP = "conversation_cleanup"
    MEMORY_EDIT = "memory_edit"
