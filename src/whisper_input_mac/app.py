import logging
import sys
from Cocoa import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
)

from .status_icon_controller import StatusIconController

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

    # Initialize status icon controller
    icon_controller = StatusIconController(
        enable_press_hold=enable_press_hold,
        enable_hotkey=enable_hotkey,
    )
    logger.info("Whisper Input app started")

    try:
        app.run()
    finally:
        icon_controller.shutdown()


if __name__ == "__main__":
    main()
