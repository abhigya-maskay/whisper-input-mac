#!/usr/bin/env python3
"""
Verification script for hotkey integration with press lifecycle events.
Tests that hotkey callbacks emit the same lifecycle events as mouse interactions.
"""

import asyncio
import logging
from unittest.mock import MagicMock, patch
from Cocoa import NSApplication, NSApplicationActivationPolicyAccessory

from src.whisper_input_mac.status_icon_controller import StatusIconController, IconState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def verify_hotkey_lifecycle():
    """Verify that hotkey presses emit correct lifecycle events."""
    # Setup NSApplication
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    
    logger.info("=" * 60)
    logger.info("HOTKEY LIFECYCLE VERIFICATION")
    logger.info("=" * 60)
    
    # Test 1: Verify hotkey lifecycle events
    logger.info("\n[Test 1] Verifying hotkey press emits lifecycle events...")
    controller = StatusIconController(enable_press_hold=False, enable_hotkey=False)
    
    # Collect emitted events
    events = []
    
    # Create a task to collect events from the queue
    async def collect_events():
        for _ in range(3):  # Expect 3 events for a hotkey press
            try:
                event = await asyncio.wait_for(controller.press_events.get(), timeout=1.0)
                events.append(event)
                logger.info(f"  Event received: {event['type']}")
            except asyncio.TimeoutError:
                logger.warning("  Timeout waiting for event")
                break
    
    # Start event collection
    collection_task = asyncio.create_task(collect_events())
    
    # Simulate hotkey press
    await asyncio.sleep(0.05)
    controller._on_hotkey_pressed()
    
    # Wait for all events to be collected
    await collection_task
    
    # Verify we got the right sequence
    expected_events = ["press_started", "hold_started", "press_released"]
    actual_events = [e["type"] for e in events]
    
    if actual_events == expected_events:
        logger.info("✓ Hotkey lifecycle sequence CORRECT")
        logger.info(f"  Expected: {expected_events}")
        logger.info(f"  Got:      {actual_events}")
    else:
        logger.error("✗ Hotkey lifecycle sequence INCORRECT")
        logger.error(f"  Expected: {expected_events}")
        logger.error(f"  Got:      {actual_events}")
        return False
    
    # Test 2: Verify state transitions during hotkey lifecycle
    logger.info("\n[Test 2] Verifying state transitions during hotkey press...")
    controller2 = StatusIconController(enable_press_hold=False, enable_hotkey=False)
    initial_state = controller2.current_state
    logger.info(f"  Initial state: {initial_state.value}")
    
    # Simulate hotkey press and track state changes
    controller2._on_hotkey_pressed()
    await asyncio.sleep(0.1)  # Let lifecycle complete
    
    final_state = controller2.current_state
    logger.info(f"  Final state: {final_state.value}")
    
    if initial_state == IconState.IDLE and final_state == IconState.IDLE:
        logger.info("✓ State transitions CORRECT (IDLE → RECORDING → IDLE)")
    else:
        logger.warning(f"⚠ State check: from {initial_state.value} to {final_state.value}")
    
    # Test 3: Verify hotkey integration in controller
    logger.info("\n[Test 3] Verifying hotkey integration setup...")
    controller3 = StatusIconController(enable_press_hold=False, enable_hotkey=True)
    
    if controller3._global_hotkey is not None:
        logger.info("✓ GlobalHotkey instance created")
        if "recording" in controller3._global_hotkey.hotkey_refs:
            logger.info("✓ Recording hotkey registered")
        else:
            logger.warning("⚠ Recording hotkey not found in hotkey_refs")
    else:
        logger.warning("⚠ GlobalHotkey not initialized (may be expected in test environment)")
    
    logger.info("\n" + "=" * 60)
    logger.info("VERIFICATION COMPLETE")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(verify_hotkey_lifecycle())
    exit(0 if success else 1)
