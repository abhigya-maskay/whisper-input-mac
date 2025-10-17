import asyncio
import logging
import sys
from Cocoa import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
)

from .audio_capture_service import AudioCaptureService
from .status_icon_controller import StatusIconController
from .orchestrator import TranscriptionOrchestrator
from .preferences import PreferencesStore
from .permissions import PermissionsCoordinator

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """
    Main entry point for Whisper Input.
    
    Usage: python -m whisper_input_mac.app [--enable-press-hold] [--enable-hotkey] [--help]
    
    Options:
      --enable-press-hold   Enable press-and-hold detection (default: True)
      --enable-hotkey       Enable global Space-bar hotkey (default: False)
      --help                Show this help message
    """
    enable_press_hold = True
    enable_hotkey = False
    
    # Simple argument parsing
    for arg in sys.argv[1:]:
        if arg == "--help" or arg == "-h":
            print(main.__doc__)
            sys.exit(0)
        elif arg == "--enable-press-hold":
            enable_press_hold = True
        elif arg == "--disable-press-hold":
            enable_press_hold = False
        elif arg == "--enable-hotkey":
            enable_hotkey = True
        elif arg == "--disable-hotkey":
            enable_hotkey = False
    
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # Log configuration
    logger.info(
        f"Whisper Input starting with press_hold={enable_press_hold}, hotkey={enable_hotkey}"
    )

    if not enable_hotkey:
        logger.info("Global hotkey disabled (use --enable-hotkey to enable)")

    # Create and run event loop for async operations
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Initialize preferences store
    preferences_store = PreferencesStore()
    logger.info("Preferences store initialized")

    # Initialize permissions coordinator (before icon controller so we can pass it)
    permissions_coordinator = PermissionsCoordinator(
        preferences_store=preferences_store,
        on_state_change=None,  # Will be set after icon_controller is created
    )
    logger.info("Permissions coordinator initialized")

    # Initialize status icon controller
    icon_controller = StatusIconController(
        enable_press_hold=enable_press_hold,
        enable_hotkey=enable_hotkey,
        preferences_store=preferences_store,
        permissions_coordinator=permissions_coordinator,
    )

    # Wire up permission state change callback to update UI
    def on_permission_state_change(status):
        logger.info(f"Permission state changed: {status.to_dict()}")
        icon_controller.update_permission_display(status)

    permissions_coordinator.on_state_change = on_permission_state_change

    # Initialize audio capture service
    audio_service = AudioCaptureService(
        loop=loop,
        on_start=lambda session_id, path: logger.debug(f"Recording started: {session_id}"),
        on_stop=lambda session_id, path: logger.debug(f"Recording stopped: {session_id}"),
        on_error=lambda error: logger.warning(f"Audio error: {error}"),
    )

    # Initialize orchestrator
    orchestrator = TranscriptionOrchestrator(
        audio_service=audio_service,
        icon_controller=icon_controller,
        permissions_coordinator=permissions_coordinator,
        preferences_store=preferences_store,
    )

    # Check permissions at startup
    loop.run_until_complete(orchestrator.startup_permissions_check())

    # Start press lifecycle handler as background task
    press_handler_task = loop.create_task(orchestrator.handle_press_lifecycle())

    logger.info("Whisper Input app started")

    try:
        app.run()
    finally:
        press_handler_task.cancel()
        orchestrator.shutdown()
        icon_controller.shutdown()
        loop.close()


if __name__ == "__main__":
    main()
