import asyncio
import logging
from typing import Callable, Optional

from Quartz import (
    CGEventMaskBit,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    CGEventTapCreate,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    CGEventTapEnable,
    CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent,
    CFRunLoopAddSource,
    kCFRunLoopCommonModes,
    CGEventGetIntegerValueField,
    kCGKeyboardEventKeycode,
    kCGKeyboardEventAutorepeat,
    CGEventGetFlags,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskShift,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskControl,
    CFRunLoopRemoveSource,
)

logger = logging.getLogger(__name__)


class GlobalHotkey:
    """Registers system-wide hotkeys using CGEvent taps."""

    # Common key codes
    SPACE = 49
    RETURN = 36
    F9 = 101

    def __init__(self):
        """Initialize hotkey manager."""
        self.hotkeys = {}
        self._event_tap = None
        self._run_loop_source = None
        self._is_monitoring = False
        self._pressed_keys = set()  # Track currently pressed hotkeys

    def register(
        self,
        key_code: int,
        modifiers: int,
        on_key_down: Optional[Callable] = None,
        on_key_up: Optional[Callable] = None,
        hotkey_id: str = "default",
        callback: Optional[Callable] = None,  # Deprecated, for backwards compatibility
    ) -> bool:
        """
        Register a global hotkey.

        Args:
            key_code: The key code (e.g., SPACE=49)
            modifiers: Modifier flags (Carbon format: cmdKey=256, shiftKey=512, optionKey=2048, controlKey=4096)
            on_key_down: Function to call when hotkey is pressed down
            on_key_up: Function to call when hotkey is released
            hotkey_id: Unique identifier for this hotkey
            callback: (Deprecated) Function to call when hotkey is pressed

        Returns:
            True if successful, False otherwise
        """
        try:
            # Backwards compatibility: if callback is provided but not on_key_down, use callback as on_key_down
            if callback is not None and on_key_down is None:
                on_key_down = callback

            # Store hotkey configuration
            self.hotkeys[hotkey_id] = {
                "key_code": key_code,
                "modifiers": modifiers,
                "on_key_down": on_key_down,
                "on_key_up": on_key_up,
            }

            # Start monitoring if not already started
            if not self._is_monitoring:
                success = self._start_monitoring()
                if not success:
                    logger.warning(
                        f"Hotkey {hotkey_id} configuration stored but monitoring could not start. "
                        "This is likely due to missing Accessibility permissions."
                    )
                    return False

            logger.info(
                f"Registered hotkey {hotkey_id}: key_code={key_code}, modifiers={modifiers}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to register hotkey {hotkey_id}: {e}")
            return False

    def unregister(self, hotkey_id: str = "default") -> bool:
        """
        Unregister a global hotkey.

        Args:
            hotkey_id: Identifier of the hotkey to unregister

        Returns:
            True if successful, False otherwise
        """
        if hotkey_id not in self.hotkeys:
            logger.warning(f"Hotkey {hotkey_id} not found")
            return False

        try:
            del self.hotkeys[hotkey_id]
            logger.info(f"Unregistered hotkey {hotkey_id}")

            # Stop monitoring if no more hotkeys
            if not self.hotkeys and self._is_monitoring:
                self._stop_monitoring()

            return True
        except Exception as e:
            logger.error(f"Failed to unregister hotkey {hotkey_id}: {e}")
            return False

    def _start_monitoring(self) -> bool:
        """
        Start monitoring keyboard events using CGEventTap.

        Returns:
            True if monitoring started successfully, False otherwise
        """
        try:
            # Create event tap callback
            def event_tap_callback(proxy, event_type, event, refcon):
                try:
                    # Get keycode and modifiers from the event
                    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    flags = CGEventGetFlags(event)

                    # Convert CGEvent flags to Carbon-style modifiers for comparison
                    carbon_modifiers = 0
                    if flags & kCGEventFlagMaskCommand:
                        carbon_modifiers |= (1 << 8)  # cmdKey
                    if flags & kCGEventFlagMaskShift:
                        carbon_modifiers |= (1 << 9)  # shiftKey
                    if flags & kCGEventFlagMaskAlternate:
                        carbon_modifiers |= (1 << 11)  # optionKey
                    if flags & kCGEventFlagMaskControl:
                        carbon_modifiers |= (1 << 12)  # controlKey

                    if event_type == kCGEventKeyDown:
                        # Ignore key repeat events (when user holds down a key)
                        is_repeat = CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat)
                        if is_repeat:
                            return event

                        # Check if this matches any registered hotkey
                        for hotkey_id, hotkey_info in self.hotkeys.items():
                            if (
                                hotkey_info["key_code"] == keycode
                                and hotkey_info["modifiers"] == carbon_modifiers
                            ):
                                # Mark as pressed and trigger on_key_down callback
                                self._pressed_keys.add(hotkey_id)
                                on_key_down = hotkey_info.get("on_key_down")
                                if on_key_down:
                                    self._dispatch_on_loop(on_key_down)
                                    logger.debug(f"Hotkey {hotkey_id} pressed down")
                                # Don't consume the event, let it pass through
                                break

                    elif event_type == kCGEventKeyUp:
                        # Check if this matches any registered hotkey that's currently pressed
                        for hotkey_id, hotkey_info in self.hotkeys.items():
                            if (
                                hotkey_info["key_code"] == keycode
                                and hotkey_info["modifiers"] == carbon_modifiers
                                and hotkey_id in self._pressed_keys
                            ):
                                # Mark as released and trigger on_key_up callback
                                self._pressed_keys.discard(hotkey_id)
                                on_key_up = hotkey_info.get("on_key_up")
                                if on_key_up:
                                    self._dispatch_on_loop(on_key_up)
                                    logger.debug(f"Hotkey {hotkey_id} released")
                                # Don't consume the event, let it pass through
                                break

                except Exception as e:
                    logger.error(f"Error in event tap callback: {e}")

                # Return the event unmodified
                return event

            # Create the event tap for both key down and key up events
            event_mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
            self._event_tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                0,  # passive listener
                event_mask,
                event_tap_callback,
                None,
            )

            if self._event_tap is None:
                logger.error(
                    "Failed to create event tap. This usually means the app doesn't have "
                    "Accessibility permissions. Grant permissions in System Settings → "
                    "Privacy & Security → Accessibility"
                )
                return False

            # Enable the event tap
            CGEventTapEnable(self._event_tap, True)

            # Create a run loop source
            self._run_loop_source = CFMachPortCreateRunLoopSource(None, self._event_tap, 0)

            # Add to the current run loop
            CFRunLoopAddSource(
                CFRunLoopGetCurrent(), self._run_loop_source, kCFRunLoopCommonModes
            )

            self._is_monitoring = True
            logger.debug("Global hotkey monitoring started")
            return True

        except Exception as e:
            logger.error(f"Failed to start monitoring: {e}")
            return False

    def _stop_monitoring(self):
        """Stop monitoring keyboard events."""
        try:
            if self._run_loop_source is not None and self._event_tap is not None:
                CGEventTapEnable(self._event_tap, False)
                CFRunLoopRemoveSource(
                    CFRunLoopGetCurrent(), self._run_loop_source, kCFRunLoopCommonModes
                )
                self._run_loop_source = None
                self._event_tap = None
                self._is_monitoring = False
                logger.debug("Global hotkey monitoring stopped")
        except Exception as e:
            logger.error(f"Failed to stop monitoring: {e}")

    def _dispatch_on_loop(self, callback: Callable):
        """Dispatch callback on the asyncio event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, just call synchronously
            callback()
            return

        # Schedule callback on the loop
        loop.call_soon_threadsafe(callback)

    def retry_setup(self) -> bool:
        """
        Retry setting up event monitoring if it failed previously.

        This is useful when Accessibility permissions are granted after initial setup.

        Returns:
            True if monitoring started successfully, False otherwise
        """
        if self._is_monitoring:
            logger.debug("Monitoring already active, no need to retry")
            return True

        if not self.hotkeys:
            logger.warning("No hotkeys registered, nothing to retry")
            return False

        logger.info("Retrying hotkey monitoring setup...")
        return self._start_monitoring()

    def cleanup(self):
        """Unregister all hotkeys and stop monitoring."""
        hotkey_ids = list(self.hotkeys.keys())
        for hotkey_id in hotkey_ids:
            self.unregister(hotkey_id)

        if self._is_monitoring:
            self._stop_monitoring()

        logger.debug("Hotkey cleanup completed")

    def __del__(self):
        """Cleanup on deletion."""
        self.cleanup()
