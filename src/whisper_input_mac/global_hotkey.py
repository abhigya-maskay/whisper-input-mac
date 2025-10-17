import asyncio
import logging
from typing import Callable, Optional

try:
    from Carbon import HIToolbox
    from Cocoa import NSEvent
    HAS_CARBON = True
except ImportError:
    HAS_CARBON = False

logger = logging.getLogger(__name__)


class GlobalHotkey:
    """Registers system-wide hotkeys that trigger callbacks."""

    # Common key codes
    SPACE = 49
    RETURN = 36

    def __init__(self):
        """Initialize hotkey manager."""
        self.hotkey_refs = {}
        self._event_handler_ref = None
        if not HAS_CARBON:
            logger.warning("Carbon framework not available; hotkey support disabled")

    def register(
        self,
        key_code: int,
        modifiers: int,
        callback: Callable,
        hotkey_id: str = "default",
    ) -> bool:
        """
        Register a global hotkey.

        Args:
            key_code: The key code (e.g., SPACE=49)
            modifiers: Modifier flags (e.g., cmdKey | optionKey)
            callback: Function to call when hotkey is pressed
            hotkey_id: Unique identifier for this hotkey

        Returns:
            True if successful, False otherwise
        """
        if not HAS_CARBON:
            logger.warning("Carbon framework not available; cannot register hotkey")
            return False

        try:
            # Create a unique event hot key ID
            hot_key_id = HIToolbox.EventHotKeyID(signature=0x57484B59, id=hash(hotkey_id) % 2**16)

            # Register the hotkey
            hot_key_ref = HIToolbox.RegisterEventHotKey(
                key_code,
                modifiers,
                hot_key_id,
                HIToolbox.GetApplicationEventTarget(),
                0,
                None,
            )

            # Store for later unregistration
            self.hotkey_refs[hotkey_id] = {
                "ref": hot_key_ref,
                "key_code": key_code,
                "modifiers": modifiers,
                "callback": callback,
                "id": hot_key_id,
            }

            logger.info(
                f"Registered hotkey {hotkey_id}: key_code={key_code}, "
                f"modifiers={modifiers}"
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
        if hotkey_id not in self.hotkey_refs:
            logger.warning(f"Hotkey {hotkey_id} not found")
            return False

        try:
            ref_info = self.hotkey_refs[hotkey_id]
            if HAS_CARBON and ref_info.get("ref"):
                HIToolbox.UnregisterEventHotKey(ref_info["ref"])
            del self.hotkey_refs[hotkey_id]
            logger.info(f"Unregistered hotkey {hotkey_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to unregister hotkey {hotkey_id}: {e}")
            return False

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

    def cleanup(self):
        """Unregister all hotkeys."""
        hotkey_ids = list(self.hotkey_refs.keys())
        for hotkey_id in hotkey_ids:
            self.unregister(hotkey_id)
        logger.debug("Hotkey cleanup completed")

    def __del__(self):
        """Cleanup on deletion."""
        self.cleanup()
