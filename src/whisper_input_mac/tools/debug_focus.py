#!/usr/bin/env python3
"""
Debug tool for testing Accessibility focus tracking.

This script monitors the currently focused UI element and prints information
about it. Switch between different applications while this script is running
to verify that the FocusObserver correctly tracks the foreground app.

Usage:
    poetry run python -m whisper_input_mac.tools.debug_focus
"""

import asyncio
import logging
import signal
import sys
import time

from whisper_input_mac.accessibility import (
    FocusObserver,
    wait_for_trusted_access,
    AccessibilityPermissionError,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class FocusDebugger:
    """Debugger for monitoring focused UI elements."""

    def __init__(self):
        """Initialize the focus debugger."""
        self.focus_observer = None
        self.is_running = False
        self.last_focus_info = None

    async def start(self):
        """Start monitoring focused elements."""
        logger.info("Starting Focus Debugger...")
        logger.info("=" * 60)

        # Initialize FocusObserver
        try:
            self.focus_observer = FocusObserver()
            logger.info("FocusObserver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize FocusObserver: {e}")
            return False

        # Check and wait for accessibility permissions
        logger.info("Checking accessibility permissions...")
        logger.info("(A system dialog may appear if permission is not granted)")

        # First check with prompt
        if not self.focus_observer.ensure_trusted(prompt=True):
            logger.warning("Accessibility permission not granted yet.")
            logger.info("Waiting for permission to be granted...")
            logger.info("Please enable accessibility in System Preferences:")
            logger.info("  System Preferences → Security & Privacy → Privacy → Accessibility")

            # Wait for permission with longer timeout
            has_access = await wait_for_trusted_access(
                self.focus_observer,
                timeout=60.0,
                poll_interval=1.0
            )

            if not has_access:
                logger.error("Accessibility permission not granted within timeout.")
                logger.error("Please grant permission and try again.")
                return False

        logger.info("Accessibility permission granted!")
        logger.info("=" * 60)
        return True

    async def monitor_focus(self, poll_interval: float = 1.0):
        """
        Monitor the focused element and print changes.

        Args:
            poll_interval: Time between focus checks in seconds
        """
        logger.info("Starting focus monitoring...")
        logger.info("Switch between different applications to test focus tracking.")
        logger.info("Press Ctrl+C to stop.\n")

        self.is_running = True
        iteration = 0

        while self.is_running:
            iteration += 1

            try:
                # Get current focused element info
                focus_info = self.focus_observer.get_focused_element()

                # Only print if focus changed or every 10 iterations
                if focus_info != self.last_focus_info or iteration % 10 == 0:
                    timestamp = time.strftime("%H:%M:%S")

                    if focus_info:
                        logger.info(
                            f"[{timestamp}] Focused Element:\n"
                            f"  Bundle ID: {focus_info.bundle_identifier or 'N/A'}\n"
                            f"  Role:      {focus_info.role or 'N/A'}\n"
                            f"  Subrole:   {focus_info.subrole or 'N/A'}"
                        )
                    else:
                        logger.info(f"[{timestamp}] No focused element detected")

                    self.last_focus_info = focus_info

            except AccessibilityPermissionError:
                logger.error("Accessibility permission was revoked!")
                logger.error("Please re-enable accessibility permission and restart.")
                break
            except Exception as e:
                logger.error(f"Error getting focused element: {e}")

            await asyncio.sleep(poll_interval)

    def stop(self):
        """Stop monitoring."""
        logger.info("\nStopping focus monitoring...")
        self.is_running = False


async def main():
    """Main entry point for the debug script."""
    debugger = FocusDebugger()

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("\nReceived interrupt signal")
        debugger.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start the debugger
    success = await debugger.start()
    if not success:
        sys.exit(1)

    # Monitor focus
    try:
        await debugger.monitor_focus(poll_interval=1.0)
    except asyncio.CancelledError:
        logger.info("Monitoring cancelled")
    finally:
        debugger.stop()
        logger.info("Focus debugger stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nExiting...")
        sys.exit(0)
