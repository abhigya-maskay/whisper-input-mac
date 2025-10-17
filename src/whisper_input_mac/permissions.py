"""Permissions coordinator for managing microphone and accessibility permissions."""

import asyncio
import logging
from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass

from .preferences import PreferencesStore, PreferenceKey

# Import PyObjC frameworks
try:
    from Cocoa import AVAudioSession, NSAlert, NSAlertFirstButtonReturn, NSAlertSecondButtonReturn
    from Quartz import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
except ImportError as e:
    raise ImportError(
        f"Required PyObjC frameworks not available: {e}. "
        "Ensure pyobjc-framework-Cocoa and pyobjc-framework-Quartz are installed."
    ) from e

logger = logging.getLogger(__name__)


class PermissionState(str, Enum):
    """Enumeration of permission states."""
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"


@dataclass
class PermissionStatus:
    """Status of all permissions."""
    microphone: PermissionState
    accessibility: PermissionState

    def all_granted(self) -> bool:
        """Check if all permissions are granted."""
        return (
            self.microphone == PermissionState.GRANTED
            and self.accessibility == PermissionState.GRANTED
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "microphone": self.microphone.value,
            "accessibility": self.accessibility.value,
        }


class PermissionsCoordinator:
    """
    Coordinates microphone and accessibility permission checks.

    This service wraps permission checking for microphone (via AVAudioSession)
    and accessibility (via AXIsProcessTrustedWithOptions), tracks state,
    persists state to preferences, and provides callbacks for UI updates.
    """

    def __init__(
        self,
        preferences_store: PreferencesStore,
        on_state_change: Optional[Callable[[PermissionStatus], None]] = None,
    ):
        """
        Initialize the permissions coordinator.

        Args:
            preferences_store: PreferencesStore instance for state persistence
            on_state_change: Optional callback(PermissionStatus) when permission state changes
        """
        self.preferences = preferences_store
        self.on_state_change = on_state_change

        # Initialize state from preferences
        self._microphone_state = PermissionState(
            self.preferences.get(PreferenceKey.MICROPHONE_STATE)
        )
        self._accessibility_state = PermissionState(
            self.preferences.get(PreferenceKey.ACCESSIBILITY_STATE)
        )

        logger.info(
            f"PermissionsCoordinator initialized: "
            f"microphone={self._microphone_state.value}, "
            f"accessibility={self._accessibility_state.value}"
        )

    def get_status(self) -> PermissionStatus:
        """
        Get current permission status.

        Returns:
            PermissionStatus with current state
        """
        return PermissionStatus(
            microphone=self._microphone_state,
            accessibility=self._accessibility_state,
        )

    async def check_microphone_permission(self, request_if_needed: bool = True) -> PermissionState:
        """
        Check microphone permission status.

        Args:
            request_if_needed: If True and permission is pending, request it from user

        Returns:
            Current microphone permission state
        """
        logger.debug(f"Checking microphone permission (request_if_needed={request_if_needed})")

        if not request_if_needed and self._microphone_state == PermissionState.PENDING:
            # Just return current state without requesting
            return self._microphone_state

        # Request permission if needed
        if self._microphone_state == PermissionState.PENDING or request_if_needed:
            granted = await self._request_microphone_permission()
            new_state = PermissionState.GRANTED if granted else PermissionState.DENIED
            self._update_microphone_state(new_state)
            return new_state

        # Already granted or denied, just return current state
        return self._microphone_state

    async def _request_microphone_permission(self) -> bool:
        """
        Request microphone permission from the user.

        Returns:
            True if granted, False if denied or timeout
        """
        logger.info("Requesting microphone permission from user...")

        permission_result = [None]
        event = asyncio.Event()

        def permission_handler(granted):
            permission_result[0] = granted
            event.set()

        # Request permission on main thread via AVAudioSession
        def request_on_main_thread():
            session = AVAudioSession.sharedInstance()
            session.requestRecordPermission_(permission_handler)

        # Execute request
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, request_on_main_thread)

        # Wait for user response with timeout
        try:
            await asyncio.wait_for(event.wait(), timeout=30.0)
            granted = permission_result[0] if permission_result[0] is not None else False
            logger.info(f"Microphone permission: {'granted' if granted else 'denied'}")
            return granted
        except asyncio.TimeoutError:
            logger.warning("Microphone permission request timed out")
            return False

    def check_accessibility_permission(self, prompt: bool = False) -> PermissionState:
        """
        Check accessibility permission status (synchronous).

        Args:
            prompt: If True, show system prompt to enable accessibility

        Returns:
            Current accessibility permission state
        """
        logger.debug(f"Checking accessibility permission (prompt={prompt})")

        try:
            options = {kAXTrustedCheckOptionPrompt: prompt}
            is_trusted = bool(AXIsProcessTrustedWithOptions(options))

            new_state = PermissionState.GRANTED if is_trusted else PermissionState.DENIED
            self._update_accessibility_state(new_state)

            return new_state

        except Exception as e:
            logger.error(f"Error checking accessibility permission: {e}")
            return self._accessibility_state

    async def wait_for_accessibility_permission(
        self,
        prompt: bool = True,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> PermissionState:
        """
        Asynchronously wait for accessibility permission to be granted.

        Args:
            prompt: If True, show system prompt on first check
            timeout: Maximum time to wait in seconds
            poll_interval: Time between checks in seconds

        Returns:
            Final accessibility permission state
        """
        logger.info(f"Waiting for accessibility permission (timeout={timeout}s)...")

        # First check with optional prompt
        if prompt:
            state = self.check_accessibility_permission(prompt=True)
            if state == PermissionState.GRANTED:
                return state
            # Give user a moment to read the prompt
            await asyncio.sleep(1.0)

        # Poll until granted or timeout
        elapsed = 0.0
        loop = asyncio.get_running_loop()

        while elapsed < timeout:
            # Run check on executor to avoid blocking
            state = await loop.run_in_executor(
                None, self.check_accessibility_permission, False
            )

            if state == PermissionState.GRANTED:
                logger.info("Accessibility permission granted")
                return state

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning(f"Accessibility permission not granted after {timeout} seconds")
        self._update_accessibility_state(PermissionState.DENIED)
        return PermissionState.DENIED

    async def ensure_ready(self, show_dialogs: bool = True) -> PermissionStatus:
        """
        Ensure all permissions are ready.

        This is the main entry point for checking permissions before recording.
        It checks both microphone and accessibility permissions, requesting them
        if needed.

        Args:
            show_dialogs: If True, show dialogs for denied permissions

        Returns:
            PermissionStatus with current state

        Raises:
            PermissionError if critical permissions are denied
        """
        logger.info("Ensuring permissions are ready...")

        # Check microphone permission
        mic_state = await self.check_microphone_permission(request_if_needed=True)
        if mic_state == PermissionState.DENIED:
            logger.error("Microphone permission denied")
            if show_dialogs:
                self._show_microphone_denied_dialog()
            raise PermissionError("Microphone permission denied")

        # Check accessibility permission
        ax_state = await self.wait_for_accessibility_permission(
            prompt=True,
            timeout=30.0,
        )
        if ax_state == PermissionState.DENIED:
            logger.error("Accessibility permission denied")
            if show_dialogs:
                await self._show_accessibility_denied_dialog()
            raise PermissionError("Accessibility permission denied")

        logger.info("All permissions granted")
        return self.get_status()

    def _show_microphone_denied_dialog(self) -> None:
        """Show alert when microphone permission is denied."""
        logger.debug("Showing microphone denied dialog")

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Microphone Access Required")
        alert.setInformativeText_(
            "Whisper Input needs microphone access to transcribe your speech. "
            "Please grant permission in System Settings → Privacy & Security → Microphone."
        )
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    async def _show_accessibility_denied_dialog(self) -> None:
        """Show alert when accessibility permission is denied."""
        logger.debug("Showing accessibility denied dialog")

        loop = asyncio.get_running_loop()

        def show_dialog():
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Accessibility Access Required")
            alert.setInformativeText_(
                "Whisper Input needs accessibility permissions to insert transcribed text into applications. "
                "\n\nPlease enable accessibility access:\n"
                "1. Open System Settings (or System Preferences)\n"
                "2. Go to Privacy & Security → Accessibility\n"
                "3. Find Whisper Input and toggle it ON"
            )
            alert.addButtonWithTitle_("Open System Settings")
            alert.addButtonWithTitle_("Cancel")

            response = alert.runModal()
            return response

        # Show dialog on main thread
        response = await loop.run_in_executor(None, show_dialog)

        # Open System Settings if user clicked first button
        if response == NSAlertFirstButtonReturn:
            logger.info("User requested to open System Settings")
            await self._open_accessibility_settings()

    async def _open_accessibility_settings(self) -> None:
        """Open System Settings to Accessibility pane."""
        try:
            import subprocess
            # macOS Ventura and later use "System Settings"
            # Earlier versions use "System Preferences"
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                check=False
            )
            logger.info("Opened System Settings → Accessibility")
        except Exception as e:
            logger.error(f"Failed to open System Settings: {e}")

    def _update_microphone_state(self, new_state: PermissionState) -> None:
        """
        Update microphone permission state.

        Args:
            new_state: New permission state
        """
        if new_state != self._microphone_state:
            logger.info(f"Microphone permission state changed: {self._microphone_state.value} → {new_state.value}")
            self._microphone_state = new_state

            # Persist to preferences
            self.preferences.set(PreferenceKey.MICROPHONE_STATE, new_state.value, save=True)

            # Notify callback
            if self.on_state_change:
                try:
                    self.on_state_change(self.get_status())
                except Exception as e:
                    logger.error(f"Error in permission state change callback: {e}")

    def _update_accessibility_state(self, new_state: PermissionState) -> None:
        """
        Update accessibility permission state.

        Args:
            new_state: New permission state
        """
        if new_state != self._accessibility_state:
            logger.info(f"Accessibility permission state changed: {self._accessibility_state.value} → {new_state.value}")
            self._accessibility_state = new_state

            # Persist to preferences
            self.preferences.set(PreferenceKey.ACCESSIBILITY_STATE, new_state.value, save=True)

            # Notify callback
            if self.on_state_change:
                try:
                    self.on_state_change(self.get_status())
                except Exception as e:
                    logger.error(f"Error in permission state change callback: {e}")

    async def refresh_all_permissions(self) -> PermissionStatus:
        """
        Refresh all permission states by checking again.

        Returns:
            Current PermissionStatus
        """
        logger.debug("Refreshing all permission states...")

        # Check microphone (non-intrusive, doesn't request)
        await self.check_microphone_permission(request_if_needed=False)

        # Check accessibility (non-intrusive, doesn't prompt)
        self.check_accessibility_permission(prompt=False)

        return self.get_status()
