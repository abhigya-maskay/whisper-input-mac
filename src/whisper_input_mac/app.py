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

    # Initialize status icon controller
    icon_controller = StatusIconController(
        enable_press_hold=enable_press_hold,
        enable_hotkey=enable_hotkey,
    )

    # Initialize audio capture service
    audio_service = AudioCaptureService(
        loop=loop,
        on_start=lambda session_id, path: logger.debug(f"Recording started: {session_id}"),
        on_stop=lambda session_id, path: logger.debug(f"Recording stopped: {session_id}"),
        on_error=lambda error: logger.warning(f"Audio error: {error}"),
    )

    # Initialize orchestrator
    orchestrator = TranscriptionOrchestrator(audio_service, icon_controller)

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
