import logging
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


def main(
    enable_press_hold: bool = True,
    enable_hotkey: bool = False,
):
    """
    Main entry point for Whisper Input.

    Args:
        enable_press_hold: Enable press-and-hold detection (default: True)
        enable_hotkey: Enable global hotkey registration (default: False)
    """
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # Initialize status icon controller
    icon_controller = StatusIconController(
        enable_press_hold=enable_press_hold,
        enable_hotkey=enable_hotkey,
    )
    logger.info("Whisper Input app started")

    app.run()


if __name__ == "__main__":
    main()
