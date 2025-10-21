"""Text injection via CGEvent keystroke injection with clipboard fallback."""

import logging
import time
from typing import Optional, Tuple

try:
    from HIServices import (  # type: ignore
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
    )
    from Quartz import (  # type: ignore
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        CGEventSetFlags,
        kCGHIDEventTap,
        kCGEventKeyDown,
        kCGEventKeyUp,
        kCGEventFlagMaskCommand,
    )
    from Cocoa import NSPasteboard, NSStringPboardType, NSString  # type: ignore
    import objc  # type: ignore
except ImportError as e:
    raise ImportError(
        f"Required PyObjC frameworks not available: {e}. "
        "Ensure pyobjc-framework-Cocoa, pyobjc-framework-ApplicationServices, "
        "and pyobjc-framework-Quartz are installed."
    ) from e

logger = logging.getLogger(__name__)


class TextInjectionError(Exception):
    """Raised when text injection fails."""

    pass


class KeyboardInjector:
    """Encapsulates CGEvent logic for keystroke injection."""

    def ensure_trusted_access(self, prompt: bool = True) -> None:
        """
        Ensure the current process is trusted by Accessibility.

        Args:
            prompt: If True, prompt user to enable accessibility if not already trusted

        Raises:
            TextInjectionError: If process is not trusted or if checking accessibility trust fails
        """
        try:
            options = {kAXTrustedCheckOptionPrompt: prompt}
            is_trusted = bool(AXIsProcessTrustedWithOptions(options))
            if not is_trusted:
                logger.warning("Process not trusted for keystroke injection")
                raise TextInjectionError("Accessibility permission not granted")
        except TextInjectionError:
            raise
        except objc.error as e:
            logger.error(f"PyObjC error checking accessibility trust: {e}")
            raise TextInjectionError(
                f"Failed to check accessibility trust: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error checking accessibility trust: {e}")
            raise TextInjectionError(
                f"Unexpected error checking accessibility trust: {e}"
            ) from e

    def send_unicode(self, text: str) -> None:
        """
        Send text via CGEvent keystroke injection with Unicode string.

        Creates a single key-down/key-up pair and injects the Unicode string
        into the keystroke event.

        Args:
            text: The text to inject

        Raises:
            TextInjectionError: If text is empty or injection fails
        """
        if not text:
            raise TextInjectionError("Cannot inject empty text")

        # Ensure we have accessibility permission (raises if not granted)
        self.ensure_trusted_access(prompt=False)

        try:
            # Create a dummy keyboard event (we'll override with Unicode)
            # Using key code 0 as placeholder since we're setting Unicode string
            key_down_event = CGEventCreateKeyboardEvent(None, 0, True)
            key_up_event = CGEventCreateKeyboardEvent(None, 0, False)

            if key_down_event is None or key_up_event is None:
                raise TextInjectionError("Failed to create keyboard events")

            # Set the Unicode string for the key event
            CGEventKeyboardSetUnicodeString(key_down_event, len(text), text)
            CGEventKeyboardSetUnicodeString(key_up_event, len(text), text)

            # Post the events to the HID event tap
            CGEventPost(kCGHIDEventTap, key_down_event)
            CGEventPost(kCGHIDEventTap, key_up_event)

            logger.debug(f"Injected {len(text)} characters via CGEvent")

        except TextInjectionError:
            raise
        except objc.error as e:
            logger.error(f"PyObjC error during keystroke injection: {e}")
            raise TextInjectionError(
                f"Keystroke injection failed: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error during keystroke injection: {e}")
            raise TextInjectionError(
                f"Unexpected error during keystroke injection: {e}"
            ) from e


class ClipboardFallback:
    """Clipboard-based text injection fallback."""

    def __init__(self, restore_clipboard: bool = True):
        """
        Initialize clipboard fallback.

        Args:
            restore_clipboard: If True, restore previous clipboard contents after paste
        """
        self.restore_clipboard = restore_clipboard

    def paste_text(self, text: str) -> bool:
        """
        Paste text via clipboard and Cmd+V keystroke.

        Writes text to NSPasteboard, issues a Command+V keystroke pair,
        and optionally restores previous clipboard contents.

        Args:
            text: The text to paste

        Returns:
            True if paste succeeded, False otherwise
        """
        if not text:
            logger.warning("Cannot paste empty text")
            return False

        previous_clipboard = None

        try:
            # Get reference to general pasteboard
            pasteboard = NSPasteboard.generalPasteboard()

            # Save previous clipboard contents if restoration is enabled
            if self.restore_clipboard:
                try:
                    previous_clipboard = pasteboard.stringForType_(NSStringPboardType)
                except Exception as e:
                    logger.debug(f"Could not save previous clipboard: {e}")

            # Clear and set new clipboard contents
            pasteboard.clearContents()
            ns_string = NSString.stringWithString_(text)
            success = pasteboard.setString_forType_(ns_string, NSStringPboardType)

            if not success:
                logger.error("Failed to write to clipboard")
                return False

            logger.debug(f"Text copied to clipboard: {len(text)} characters")

            # Simulate Cmd+V keystroke
            # Check if we have accessibility permission for keystrokes
            options = {kAXTrustedCheckOptionPrompt: False}
            is_trusted = bool(AXIsProcessTrustedWithOptions(options))

            if not is_trusted:
                logger.warning(
                    "Accessibility permission not available - clipboard set but "
                    "cannot simulate Cmd+V. User must paste manually."
                )
                return True  # Partial success - clipboard is set

            try:
                # Create V key events
                v_key_code = 0x09  # Virtual key code for 'V'
                v_down = CGEventCreateKeyboardEvent(None, v_key_code, True)
                v_up = CGEventCreateKeyboardEvent(None, v_key_code, False)

                # Set Command flag on both V key events
                CGEventSetFlags(v_down, kCGEventFlagMaskCommand)
                CGEventSetFlags(v_up, kCGEventFlagMaskCommand)

                # Post the Cmd+V events
                CGEventPost(kCGHIDEventTap, v_down)
                CGEventPost(kCGHIDEventTap, v_up)

                logger.debug("Simulated Cmd+V keystroke")

                # Wait a moment for the paste to complete before restoring clipboard
                # This ensures the application has time to read from the clipboard
                time.sleep(0.05)  # 50ms should be enough

            except Exception as e:
                logger.warning(f"Failed to simulate Cmd+V: {e}")
                # Still return True since clipboard is set
                return True

            # Restore previous clipboard if enabled
            if self.restore_clipboard and previous_clipboard is not None:
                try:
                    pasteboard.clearContents()
                    pasteboard.setString_forType_(
                        previous_clipboard, NSStringPboardType
                    )
                    logger.debug("Restored previous clipboard contents")
                except Exception as e:
                    logger.debug(f"Could not restore previous clipboard: {e}")

            return True

        except objc.error as e:
            logger.error(f"PyObjC error during clipboard paste: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during clipboard paste: {e}")
            return False


class TextInjector:
    """Facade for text injection that coordinates keystroke and clipboard approaches."""

    def __init__(self, restore_clipboard: bool = True):
        """
        Initialize text injector.

        Args:
            restore_clipboard: If True, restore previous clipboard after fallback paste
        """
        self.keyboard_injector = KeyboardInjector()
        self.clipboard_fallback = ClipboardFallback(restore_clipboard=restore_clipboard)

    def send_text(
        self, text: str, prefer_clipboard: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Send text using keystroke injection or clipboard fallback.

        Tries keystroke injection first when accessibility is trusted,
        falls back to clipboard on exceptions.

        Args:
            text: The text to inject
            prefer_clipboard: If True, skip keystroke injection and use clipboard

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if not text:
            return False, "Cannot inject empty text"

        # If clipboard is preferred, use it directly
        if prefer_clipboard:
            logger.debug("Using clipboard method as preferred")
            success = self.clipboard_fallback.paste_text(text)
            return success, None if success else "Clipboard paste failed"

        # Try keystroke injection first
        try:
            self.keyboard_injector.send_unicode(text)
            logger.info(f"Text injected via keystroke: {len(text)} characters")
            return True, None
        except TextInjectionError as e:
            logger.debug(f"Keystroke injection failed, falling back to clipboard: {e}")

        # Fall back to clipboard
        success = self.clipboard_fallback.paste_text(text)
        if success:
            logger.info(
                f"Text injected via clipboard fallback: {len(text)} characters"
            )
            return True, None
        else:
            return False, "Both keystroke injection and clipboard fallback failed"
