"""Focus observer for tracking the focused UI element using Accessibility APIs."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

try:
    from HIServices import (  # type: ignore
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        kAXFocusedUIElementAttribute,
        kAXFocusedApplicationAttribute,
        kAXRoleAttribute,
        kAXSubroleAttribute,
    )
    import objc  # type: ignore
except ImportError as e:
    raise ImportError(
        f"Required PyObjC frameworks not available: {e}. "
        "Ensure pyobjc-framework-ApplicationServices is installed."
    ) from e

logger = logging.getLogger(__name__)


class AccessibilityPermissionError(Exception):
    """Raised when accessibility permission is not granted."""

    pass


@dataclass
class FocusedElementInfo:
    """Information about the currently focused UI element."""

    bundle_identifier: Optional[str] = None
    role: Optional[str] = None
    subrole: Optional[str] = None

    @staticmethod
    def _normalize_value(value) -> Optional[str]:
        """Normalize a PyObjC value to string or None."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return str(value)
        except Exception:
            return None


class FocusObserver:
    """Encapsulates focus discovery logic using Accessibility APIs."""

    def __init__(self) -> None:
        """Initialize the focus observer."""
        try:
            self._system_wide = AXUIElementCreateSystemWide()
            logger.debug("FocusObserver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize FocusObserver: {e}")
            raise

    def ensure_trusted(self, prompt: bool = True) -> bool:
        """
        Check if the current process is trusted by Accessibility.

        Args:
            prompt: If True, prompt user to enable accessibility if not already trusted

        Returns:
            True if process is trusted, False otherwise
        """
        try:
            options = {kAXTrustedCheckOptionPrompt: prompt}
            is_trusted = bool(AXIsProcessTrustedWithOptions(options))
            if not is_trusted:
                logger.warning("Process not trusted by Accessibility API")
            return is_trusted
        except objc.error as e:
            logger.error(f"PyObjC error checking accessibility trust: {e}")
            raise AccessibilityPermissionError(
                f"Failed to check accessibility trust: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error checking accessibility trust: {e}")
            raise AccessibilityPermissionError(
                f"Unexpected error checking accessibility trust: {e}"
            ) from e

    def get_focused_element(self) -> Optional[FocusedElementInfo]:
        """
        Get information about the currently focused UI element.

        Returns:
            FocusedElementInfo object or None if no element is focused

        Raises:
            AccessibilityPermissionError if accessibility permission is not granted
        """
        if not self.ensure_trusted(prompt=False):
            raise AccessibilityPermissionError("Accessibility permission not granted")

        try:
            # Get focused element
            focused_element, error = AXUIElementCopyAttributeValue(
                self._system_wide, kAXFocusedUIElementAttribute, None
            )
            if error or focused_element is None:
                logger.debug("No focused element found")
                return None

            # Get focused application
            focused_app, error = AXUIElementCopyAttributeValue(
                self._system_wide, kAXFocusedApplicationAttribute, None
            )
            if error or focused_app is None:
                logger.debug("Could not get focused application")
                return None

            bundle_id = self._get_attribute(
                focused_app, "AXBundleIdentifier"
            )
            role = self._get_attribute(focused_element, kAXRoleAttribute)
            subrole = self._get_attribute(focused_element, kAXSubroleAttribute)

            info = FocusedElementInfo(
                bundle_identifier=FocusedElementInfo._normalize_value(bundle_id),
                role=FocusedElementInfo._normalize_value(role),
                subrole=FocusedElementInfo._normalize_value(subrole),
            )
            logger.debug(f"Focused element info: {info}")
            return info

        except objc.error as e:
            logger.error(f"PyObjC error getting focused element: {e}")
            raise AccessibilityPermissionError(
                f"Failed to get focused element: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error getting focused element: {e}")
            return None

    @staticmethod
    def _get_attribute(element, attribute_key):
        """
        Get an attribute from a UI element.

        Args:
            element: The UI element
            attribute_key: The attribute key to retrieve

        Returns:
            The attribute value or None if not available
        """
        try:
            value, error = AXUIElementCopyAttributeValue(element, attribute_key, None)
            if error:
                logger.debug(f"Error getting attribute {attribute_key}: {error}")
                return None
            return value
        except Exception as e:
            logger.debug(f"Exception getting attribute {attribute_key}: {e}")
            return None


async def wait_for_trusted_access(
    focus_observer: Optional[FocusObserver] = None,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """
    Asynchronously wait until accessibility permission is granted.

    Polls ensure_trusted() on a background executor until permissions are granted
    or timeout is reached. This allows non-blocking waiting for user to enable
    accessibility permissions in system settings.

    Args:
        focus_observer: FocusObserver instance to check. If None, creates new instance.
        timeout: Maximum time to wait in seconds (default: 30)
        poll_interval: Time between permission checks in seconds (default: 0.5)

    Returns:
        True if permission granted within timeout, False otherwise

    Raises:
        AccessibilityPermissionError: If FocusObserver cannot be created
    """
    if focus_observer is None:
        try:
            focus_observer = FocusObserver()
        except Exception as e:
            logger.error(f"Failed to create FocusObserver: {e}")
            raise AccessibilityPermissionError(
                f"Failed to create FocusObserver: {e}"
            ) from e

    loop = asyncio.get_running_loop()
    elapsed = 0.0

    try:
        while elapsed < timeout:
            try:
                # Run blocking ensure_trusted check on background executor
                is_trusted = await loop.run_in_executor(
                    None, focus_observer.ensure_trusted, False
                )
                if is_trusted:
                    logger.info("Accessibility permission granted")
                    return True
            except AccessibilityPermissionError:
                # Still not trusted, continue polling
                pass
            except Exception as e:
                logger.warning(f"Error checking accessibility trust: {e}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning(
            f"Accessibility permission not granted after {timeout} seconds"
        )
        return False

    except asyncio.CancelledError:
        logger.debug("wait_for_trusted_access cancelled")
        raise
