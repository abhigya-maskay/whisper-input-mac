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


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # Initialize status icon controller
    icon_controller = StatusIconController()
    logger.info("Whisper Input app started")

    app.run()


if __name__ == "__main__":
    main()
