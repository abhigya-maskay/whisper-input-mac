import asyncio
import logging
from enum import Enum
from typing import Optional, Callable

from Cocoa import (
    NSStatusBar,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSProgressIndicator,
    NSView,
    NSRect,
)

from .icon_utils import create_idle_icon, create_recording_icon, create_busy_icon, add_warning_badge
from .press_hold_detector import PressHoldDetector
from .global_hotkey import GlobalHotkey
from .preferences import PreferencesStore
from .permissions import PermissionsCoordinator, PermissionStatus, PermissionState

logger = logging.getLogger(__name__)


class IconState(Enum):
    """Enum for status icon states."""
    IDLE = "idle"
    RECORDING = "recording"
    BUSY = "busy"


class StatusIconController:
    """Controller managing status bar icon and state transitions."""

    def __init__(
        self,
        enable_press_hold: bool = True,
        enable_hotkey: bool = False,
        preferences_store: Optional[PreferencesStore] = None,
        permissions_coordinator: Optional[PermissionsCoordinator] = None,
    ):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.current_state = IconState.IDLE
        self._spinner_view: Optional[NSView] = None
        self._spinner: Optional[NSProgressIndicator] = None
        self._debounce_task: Optional[asyncio.Task] = None
        self._debounce_delay = 0.1

        # Press lifecycle event queue for downstream consumers (lazy-initialized)
        self._press_events: Optional[asyncio.Queue] = None

        # Cache icons
        self.icons = {
            IconState.IDLE: create_idle_icon(),
            IconState.RECORDING: create_recording_icon(),
            IconState.BUSY: create_busy_icon(),
        }

        # Press-hold detection
        self._press_hold_detector: Optional[PressHoldDetector] = None
        self._enable_press_hold = enable_press_hold
        self._enable_hotkey = enable_hotkey

        # Global hotkey
        self._global_hotkey: Optional[GlobalHotkey] = None

        # Preferences and permissions
        self.preferences_store = preferences_store
        self.permissions_coordinator = permissions_coordinator
        self._preferences_window_controller = None
        self._permission_status_item: Optional[NSMenuItem] = None

        self._setup_menu()
        self._set_state_immediate(IconState.IDLE)

        # Start press-hold detection if enabled
        if self._enable_press_hold:
            self._setup_press_hold_detector()

        # Setup global hotkey if enabled
        if self._enable_hotkey:
            self._setup_global_hotkey()

    def _setup_press_hold_detector(self):
        """Setup press-hold detection on the status button."""
        try:
            button = self.status_item.button()
            if button is None:
                logger.warning("Status button is None, skipping press-hold detection setup")
                return
            
            self._press_hold_detector = PressHoldDetector(button, hold_threshold=0.35)
            
            # Wire callbacks
            self._press_hold_detector.on_press_start = self._on_press_start
            self._press_hold_detector.on_hold_threshold = self._on_hold_threshold
            self._press_hold_detector.on_press_end = self._on_press_end
            
            self._press_hold_detector.start()
            logger.debug("Press-hold detector initialized")
        except Exception as e:
            logger.warning(f"Failed to setup press-hold detector: {e}")

    def _setup_global_hotkey(self):
        """Setup global hotkey registration."""
        try:
            self._global_hotkey = GlobalHotkey()
            
            # Register Space key as the default hotkey for recording
            # Using Space key (49) with no modifiers
            result = self._global_hotkey.register(
                key_code=GlobalHotkey.SPACE,
                modifiers=0,
                callback=self._on_hotkey_pressed,
                hotkey_id="recording",
            )
            
            if result:
                logger.debug("Global hotkey registered for Space key")
            else:
                logger.warning("Failed to register global hotkey")
        except Exception as e:
            logger.warning(f"Failed to setup global hotkey: {e}")

    def _on_hotkey_pressed(self):
        """Handle global hotkey press by emitting press lifecycle events."""
        try:
            loop = asyncio.get_running_loop()
            # Emit press lifecycle sequence to match mouse interaction behavior
            asyncio.create_task(self._hotkey_press_lifecycle())
        except RuntimeError:
            logger.warning("No running loop for hotkey_pressed event")

    async def _hotkey_press_lifecycle(self):
        """Simulate press-and-hold lifecycle for hotkey."""
        # Emit press start
        await self._emit_press_event("press_started")
        
        # Emit hold threshold to trigger recording entry
        await self._emit_press_event("hold_started")
        
        # Emit press release to trigger recording exit
        await self._emit_press_event("press_released")

    @property
    def press_events(self) -> asyncio.Queue:
        """Get the press events queue, lazily initializing it if needed."""
        if self._press_events is None:
            try:
                self._press_events = asyncio.Queue()
            except RuntimeError:
                # No event loop, create a dummy queue-like object
                logger.warning("No event loop available for press_events queue")
                self._press_events = asyncio.Queue()
        return self._press_events

    async def _emit_press_event(self, event_type: str):
        """Emit a press lifecycle event to the event queue."""
        try:
            await self.press_events.put({"type": event_type})
            logger.debug(f"Emitted press event: {event_type}")
        except Exception as e:
            logger.warning(f"Failed to emit press event: {e}")

    def _on_press_start(self):
        """Handle press start event."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit_press_event("press_started"))
        except RuntimeError:
            logger.warning("No running loop for press_started event")

    def _on_hold_threshold(self):
        """Handle hold threshold reached event."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit_press_event("hold_started"))
        except RuntimeError:
            logger.warning("No running loop for hold_started event")
        
        self.enter_recording()

    def _on_press_end(self):
        """Handle press end event."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit_press_event("press_released"))
        except RuntimeError:
            logger.warning("No running loop for press_released event")
        
        self.exit_recording()

    def _setup_menu(self):
        """Setup menu for status item."""
        menu = NSMenu.alloc().init()

        # About menu item
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Whisper Input", "showAbout:", ""
        )
        about_item.setTarget_(self)
        menu.addItem_(about_item)

        # Separator
        menu.addItem_(NSMenuItem.separatorItem())

        # Preferences menu item
        prefs_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Preferences…", "showPreferences:", ","
        )
        prefs_item.setTarget_(self)
        menu.addItem_(prefs_item)

        # Separator
        menu.addItem_(NSMenuItem.separatorItem())

        # Permission status item (disabled, shows current permission state)
        self._permission_status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Permissions: Checking...", None, ""
        )
        self._permission_status_item.setEnabled_(False)
        menu.addItem_(self._permission_status_item)

        # Update permission status
        self._update_permission_status()

        # Separator
        menu.addItem_(NSMenuItem.separatorItem())

        # Quit menu item
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Whisper Input", "terminate:", "q"
        )
        menu.addItem_(quit_item)

        self.status_item.setMenu_(menu)

    def _set_state_immediate(self, state: IconState):
        """Immediately update icon and tooltip without debouncing."""
        self.current_state = state
        button = self.status_item.button()

        if state == IconState.BUSY:
            self._start_spinner()
        else:
            self._stop_spinner()

        # Get base icon
        icon = self.icons[state]

        # Check if permissions are denied and add warning badge
        if self._should_show_permission_warning():
            icon = add_warning_badge(icon)

        # Update icon
        button.setImage_(icon)

        # Update tooltip based on state and permissions
        tooltip = self._get_tooltip_for_state(state)
        button.setToolTip_(tooltip)

        logger.debug(f"State changed to {state.value}")

    def _should_show_permission_warning(self) -> bool:
        """
        Check if permission warning badge should be shown.

        Returns:
            True if any permission is denied, False otherwise
        """
        if self.permissions_coordinator is None:
            return False

        try:
            status = self.permissions_coordinator.get_status()
            return (
                status.microphone == PermissionState.DENIED or
                status.accessibility == PermissionState.DENIED
            )
        except Exception as e:
            logger.debug(f"Failed to check permissions for warning badge: {e}")
            return False

    def _get_tooltip_for_state(self, state: IconState) -> str:
        """
        Get tooltip text for a given state, considering permissions.

        Args:
            state: Current icon state

        Returns:
            Tooltip string
        """
        # Check permissions if available
        if self.permissions_coordinator is not None:
            try:
                status = self.permissions_coordinator.get_status()

                # Check for permission blockers
                if status.microphone == PermissionState.DENIED:
                    return "Whisper Input - Grant microphone access to continue"
                elif status.microphone == PermissionState.PENDING:
                    return "Whisper Input - Microphone permission needed"

                if status.accessibility == PermissionState.DENIED:
                    return "Whisper Input - Grant accessibility access to continue"
                elif status.accessibility == PermissionState.PENDING:
                    return "Whisper Input - Accessibility permission needed"

            except Exception as e:
                logger.debug(f"Failed to check permissions for tooltip: {e}")

        # Default tooltips when permissions are OK or unavailable
        tooltips = {
            IconState.IDLE: "Whisper Input - Press and hold to speak",
            IconState.RECORDING: "Whisper Input - Recording...",
            IconState.BUSY: "Whisper Input - Transcribing...",
        }
        return tooltips.get(state, "Whisper Input")

    def _start_spinner(self):
        """Start animated spinner in the status item button."""
        if self._spinner is not None:
            return

        button = self.status_item.button()
        button_frame = button.frame()

        # Create container view for spinner
        self._spinner_view = NSView.alloc().initWithFrame_(button_frame)

        # Create progress indicator (spinner)
        spinner_size = button_frame.size.height - 4
        spinner_rect = NSRect(
            (2, (button_frame.size.height - spinner_size) / 2),
            (spinner_size, spinner_size),
        )
        self._spinner = NSProgressIndicator.alloc().initWithFrame_(spinner_rect)
        self._spinner.setIndeterminate_(True)
        self._spinner.startAnimation_(None)

        self._spinner_view.addSubview_(self._spinner)
        button.addSubview_(self._spinner_view)
        logger.debug("Started spinner")

    def _stop_spinner(self):
        """Stop and remove animated spinner."""
        if self._spinner is None:
            return

        self._spinner.stopAnimation_(None)
        self._spinner_view.removeFromSuperview()
        self._spinner = None
        self._spinner_view = None
        logger.debug("Stopped spinner")

    async def _debounced_set_state(self, state: IconState):
        """Set state with debouncing to prevent flicker on rapid transitions."""
        # Cancel previous debounce task if any
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()

        # Create new debounce task
        async def delayed_set():
            await asyncio.sleep(self._debounce_delay)
            self._set_state_immediate(state)

        self._debounce_task = asyncio.create_task(delayed_set())

    def set_state(self, state: IconState):
        """
        Set the icon state. Debounces to prevent flicker on rapid transitions.
        Can be called sync or within an event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._debounced_set_state(state))
        except RuntimeError:
            # No running event loop, set immediately
            self._set_state_immediate(state)

    def enter_recording(self):
        """Enter recording state."""
        self.set_state(IconState.RECORDING)
        logger.info("Entered recording state")

    def exit_recording(self):
        """Exit recording state back to idle."""
        self.set_state(IconState.IDLE)
        logger.info("Exited recording state")

    def set_busy(self):
        """Set busy state for transcription."""
        self.set_state(IconState.BUSY)
        logger.info("Set to busy state")

    def set_idle(self):
        """Set idle state."""
        self.set_state(IconState.IDLE)
        logger.info("Set to idle state")

    def showAbout_(self, sender) -> None:
        """Show the About panel."""
        from .preferences_window import show_about_panel
        try:
            show_about_panel()
        except Exception as e:
            logger.error(f"Failed to show about panel: {e}")

    def showPreferences_(self, sender) -> None:
        """Show the Preferences window."""
        if self.preferences_store is None:
            logger.warning("Preferences store not available")
            return

        try:
            from .preferences_window import PreferencesWindowController

            if self._preferences_window_controller is None:
                self._preferences_window_controller = PreferencesWindowController(
                    preferences_store=self.preferences_store,
                    on_apply=self._on_preferences_applied,
                )

            self._preferences_window_controller.show()
        except Exception as e:
            logger.error(f"Failed to show preferences window: {e}")

    def _on_preferences_applied(self, hotkey_config, auto_punctuation, language) -> None:
        """Handle preferences being applied."""
        logger.info(f"Preferences applied: hotkey={hotkey_config}, auto_punct={auto_punctuation}, language={language}")

        # Apply hotkey changes to global_hotkey
        if self._global_hotkey and self._enable_hotkey:
            try:
                # Unregister old hotkey
                self._global_hotkey.cleanup()

                # Re-register with new hotkey
                self._global_hotkey = GlobalHotkey()
                result = self._global_hotkey.register(
                    key_code=hotkey_config.keycode,
                    modifiers=hotkey_config.modifiers,
                    callback=self._on_hotkey_pressed,
                    hotkey_id="recording",
                )

                if result:
                    logger.info(f"Global hotkey updated: keycode={hotkey_config.keycode}, modifiers={hotkey_config.modifiers}")
                else:
                    logger.error("Failed to update global hotkey")
            except Exception as e:
                logger.error(f"Error updating global hotkey: {e}")

        # Note: Auto-punctuation and language changes are persisted to PreferencesStore
        # and propagated to the orchestrator via preference change listeners.
        # The orchestrator reloads the transcriber when language changes.

    def _update_permission_status(self) -> None:
        """Update the permission status menu item."""
        if self._permission_status_item is None:
            return

        if self.permissions_coordinator is None:
            self._permission_status_item.setTitle_("Permissions: Unknown")
            return

        try:
            status = self.permissions_coordinator.get_status()
            mic_status = status.microphone.value.capitalize()
            ax_status = status.accessibility.value.capitalize()

            status_text = f"Mic: {mic_status}, Accessibility: {ax_status}"
            self._permission_status_item.setTitle_(status_text)

            logger.debug(f"Permission status updated: {status_text}")
        except Exception as e:
            logger.error(f"Failed to update permission status: {e}")
            self._permission_status_item.setTitle_("Permissions: Error")

    def update_permission_display(self, status: PermissionStatus) -> None:
        """
        Update permission status display (called from permission state change callback).

        Args:
            status: Current PermissionStatus
        """
        self._update_permission_status()

        # Refresh icon to show/hide warning badge based on new permission state
        self._set_state_immediate(self.current_state)

        logger.debug(f"Permission display updated: {status.to_dict()}")

    def show_permission_error(self, error_message: str) -> None:
        """
        Show a user-facing error dialog for permission issues.

        Args:
            error_message: Error message describing the permission issue
        """
        from Cocoa import NSAlert, NSAlertFirstButtonReturn
        import subprocess

        logger.info(f"Showing permission error dialog: {error_message}")

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Permission Required")

        # Customize message based on error type
        if "microphone" in error_message.lower():
            alert.setInformativeText_(
                "Whisper Input needs microphone access to record your voice.\n\n"
                "To enable:\n"
                "1. Open System Settings\n"
                "2. Go to Privacy & Security → Microphone\n"
                "3. Enable Whisper Input"
            )
            alert.addButtonWithTitle_("Open System Settings")
            alert.addButtonWithTitle_("Cancel")

            response = alert.runModal()
            if response == NSAlertFirstButtonReturn:
                try:
                    subprocess.run(
                        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"],
                        check=False
                    )
                except Exception as e:
                    logger.error(f"Failed to open System Settings: {e}")

        elif "accessibility" in error_message.lower():
            alert.setInformativeText_(
                "Whisper Input needs accessibility permissions to insert transcribed text.\n\n"
                "To enable:\n"
                "1. Open System Settings\n"
                "2. Go to Privacy & Security → Accessibility\n"
                "3. Find Whisper Input and toggle it ON"
            )
            alert.addButtonWithTitle_("Open System Settings")
            alert.addButtonWithTitle_("Cancel")

            response = alert.runModal()
            if response == NSAlertFirstButtonReturn:
                try:
                    subprocess.run(
                        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                        check=False
                    )
                except Exception as e:
                    logger.error(f"Failed to open System Settings: {e}")
        else:
            # Generic permission error
            alert.setInformativeText_(
                f"{error_message}\n\n"
                "Please check your system permissions in System Settings → Privacy & Security."
            )
            alert.addButtonWithTitle_("OK")
            alert.runModal()

    def shutdown(self):
        """Clean up resources."""
        if self._press_hold_detector is not None:
            self._press_hold_detector.stop()
            logger.debug("Press-hold detector stopped")

        if self._global_hotkey is not None:
            self._global_hotkey.cleanup()
            logger.debug("Global hotkey cleaned up")

    @property
    def status_button(self):
        """Get the status bar button."""
        return self.status_item.button()

    def __del__(self):
        """Cleanup on deletion."""
        self.shutdown()
