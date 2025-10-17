#!/usr/bin/env python3
"""
Debug tool for testing text injection via CGEvent and clipboard fallback.

This script tests the TextInjector by attempting to inject sample text
into a focused text field. It demonstrates both keystroke injection and
clipboard fallback methods.

Usage:
    1. Open a text editor or any application with a text field
    2. Focus on the text field (click inside it)
    3. Run: poetry run python -m whisper_input_mac.tools.debug_injection
    4. The script will attempt to inject "Hello from Whisper Input" into the field

The script will:
- Check for accessibility permissions
- Test keystroke injection via CGEvent
- Test clipboard fallback if keystroke injection fails
- Report which method was used and whether it succeeded
"""

import asyncio
import logging
import signal
import sys
import time

from whisper_input_mac.text_injector import TextInjector, TextInjectionError
from whisper_input_mac.accessibility import FocusObserver, wait_for_trusted_access

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class InjectionDebugger:
    """Debugger for testing text injection methods."""

    def __init__(self):
        """Initialize the injection debugger."""
        self.text_injector = None
        self.focus_observer = None

    async def start(self):
        """Initialize components and check permissions."""
        logger.info("Starting Text Injection Debugger...")
        logger.info("=" * 70)

        # Initialize TextInjector
        try:
            self.text_injector = TextInjector(restore_clipboard=True)
            logger.info("TextInjector initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize TextInjector: {e}")
            return False

        # Initialize FocusObserver for checking accessibility permissions
        try:
            self.focus_observer = FocusObserver()
            logger.info("FocusObserver initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize FocusObserver: {e}")
            # Continue without FocusObserver - we can still test clipboard

        # Check accessibility permissions
        logger.info("Checking accessibility permissions...")
        logger.info("(A system dialog may appear if permission is not granted)")

        if self.focus_observer:
            # First check with prompt
            if not self.focus_observer.ensure_trusted(prompt=True):
                logger.warning("Accessibility permission not granted yet.")
                logger.info("Waiting for permission to be granted...")
                logger.info("Please enable accessibility in System Settings:")
                logger.info("  System Settings → Privacy & Security → Accessibility")
                logger.info("  Add and enable this Python/Terminal application")

                # Wait for permission with timeout
                has_access = await wait_for_trusted_access(
                    self.focus_observer,
                    timeout=60.0,
                    poll_interval=1.0
                )

                if has_access:
                    logger.info("Accessibility permission granted!")
                else:
                    logger.warning(
                        "Accessibility permission not granted within timeout."
                    )
                    logger.warning(
                        "Keystroke injection will not work. "
                        "Only clipboard fallback will be tested."
                    )
            else:
                logger.info("Accessibility permission already granted!")
        else:
            logger.warning(
                "FocusObserver not available. "
                "Cannot verify accessibility permissions."
            )

        logger.info("=" * 70)
        return True

    async def test_injection(self, test_text: str = "Hello from Whisper Input"):
        """
        Test text injection with the provided text.

        Args:
            test_text: The text to inject (default: "Hello from Whisper Input")
        """
        logger.info("\nPreparing to test text injection...")
        logger.info(f"Test text: '{test_text}'")
        logger.info("=" * 70)

        # Give user time to focus on a text field
        logger.info("Please focus on a text field or text editor now...")
        for i in range(5, 0, -1):
            logger.info(f"Injecting in {i} seconds...")
            await asyncio.sleep(1)

        # Show focused element info if available
        if self.focus_observer:
            try:
                focused_info = self.focus_observer.get_focused_element()
                if focused_info:
                    logger.info("\nCurrently focused element:")
                    logger.info(f"  Bundle ID: {focused_info.bundle_identifier or 'N/A'}")
                    logger.info(f"  Role:      {focused_info.role or 'N/A'}")
                    logger.info(f"  Subrole:   {focused_info.subrole or 'N/A'}")
                else:
                    logger.warning("Could not detect focused element")
            except Exception as e:
                logger.debug(f"Failed to get focused element info: {e}")

        logger.info("\n" + "=" * 70)
        logger.info("Attempting text injection...")

        # Attempt to inject text
        try:
            success, error_msg = self.text_injector.send_text(test_text)

            if success:
                logger.info("✓ Text injection SUCCEEDED")
                logger.info(f"  Injected: '{test_text}'")
                logger.info(
                    "  The text should now appear in your focused text field."
                )
            else:
                logger.error("✗ Text injection FAILED")
                logger.error(f"  Error: {error_msg}")
                logger.error(
                    "  Make sure accessibility permissions are granted and "
                    "a text field is focused."
                )

        except Exception as e:
            logger.error(f"✗ Unexpected error during text injection: {e}")

        logger.info("=" * 70)

    async def test_keystroke_only(self, test_text: str = "Keystroke test"):
        """
        Test keystroke injection directly (without clipboard fallback).

        Args:
            test_text: The text to inject
        """
        logger.info("\nTesting KEYSTROKE INJECTION only...")
        logger.info(f"Test text: '{test_text}'")
        logger.info("=" * 70)

        logger.info("Please focus on a text field or text editor now...")
        for i in range(3, 0, -1):
            logger.info(f"Injecting in {i} seconds...")
            await asyncio.sleep(1)

        try:
            self.text_injector.keyboard_injector.send_unicode(test_text)
            logger.info("✓ Keystroke injection SUCCEEDED")
            logger.info(f"  Injected: '{test_text}'")
        except TextInjectionError as e:
            logger.error(f"✗ Keystroke injection FAILED: {e}")
        except Exception as e:
            logger.error(f"✗ Unexpected error: {e}")

        logger.info("=" * 70)

    async def test_clipboard_only(self, test_text: str = "Clipboard test"):
        """
        Test clipboard fallback directly (without keystroke injection).

        Args:
            test_text: The text to inject
        """
        logger.info("\nTesting CLIPBOARD FALLBACK only...")
        logger.info(f"Test text: '{test_text}'")
        logger.info("=" * 70)

        logger.info("Please focus on a text field or text editor now...")
        for i in range(3, 0, -1):
            logger.info(f"Pasting in {i} seconds...")
            await asyncio.sleep(1)

        success = self.text_injector.clipboard_fallback.paste_text(test_text)

        if success:
            logger.info("✓ Clipboard fallback SUCCEEDED")
            logger.info(f"  Pasted: '{test_text}'")
        else:
            logger.error("✗ Clipboard fallback FAILED")

        logger.info("=" * 70)

    async def run_all_tests(self):
        """Run all injection tests in sequence."""
        # Test 1: Normal injection (tries keystroke, falls back to clipboard)
        await self.test_injection("Test 1: Hello from Whisper Input")
        await asyncio.sleep(2)

        # Test 2: Keystroke only
        await self.test_keystroke_only("Test 2: Keystroke injection")
        await asyncio.sleep(2)

        # Test 3: Clipboard only
        await self.test_clipboard_only("Test 3: Clipboard fallback")

        logger.info("\nAll tests completed!")
        logger.info(
            "Check your text field to verify which methods succeeded."
        )


async def main():
    """Main entry point for the debug script."""
    debugger = InjectionDebugger()

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("\nReceived interrupt signal")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start the debugger
    success = await debugger.start()
    if not success:
        logger.error("Failed to initialize debugger")
        sys.exit(1)

    # Run all tests
    try:
        await debugger.run_all_tests()
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
    except Exception as e:
        logger.error(f"Error during tests: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nExiting...")
        sys.exit(0)
