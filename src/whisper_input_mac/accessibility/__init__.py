"""Accessibility module for macOS focus element tracking."""

from .focus_observer import (
    FocusObserver,
    FocusedElementInfo,
    AccessibilityPermissionError,
    wait_for_trusted_access,
)

__all__ = [
    "FocusObserver",
    "FocusedElementInfo",
    "AccessibilityPermissionError",
    "wait_for_trusted_access",
]
