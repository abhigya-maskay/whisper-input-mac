import asyncio
import logging
import os
import select
import signal
import sys
import threading
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
      --enable-hotkey       Enable global F9 hotkey (default: True)
      --help                Show this help message
    """
    enable_press_hold = True
    enable_hotkey = True
    
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
    else:
        logger.info("Global hotkey enabled (use --disable-hotkey to disable)")

    # Create event loop for async operations
    loop = asyncio.new_event_loop()

    # Start asyncio event loop in a background thread
    def run_async_loop(loop):
        asyncio.set_event_loop(loop)
        logger.debug("Asyncio event loop thread started")
        loop.run_forever()
        logger.debug("Asyncio event loop thread stopped")

    loop_thread = threading.Thread(target=run_async_loop, args=(loop,), daemon=True)
    loop_thread.start()
    logger.info("Asyncio event loop started in background thread")

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
        event_loop=loop,
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

    # Check permissions at startup (schedule on the running loop)
    startup_future = asyncio.run_coroutine_threadsafe(
        orchestrator.startup_permissions_check(),
        loop
    )
    # Wait for startup to complete
    try:
        startup_future.result(timeout=35.0)  # Allow time for permission prompts
    except Exception as e:
        logger.warning(f"Startup permissions check failed or timed out: {e}")

    # Start press lifecycle handler as background task
    press_handler_task = asyncio.run_coroutine_threadsafe(
        orchestrator.handle_press_lifecycle(),
        loop
    )

    logger.info("Whisper Input app started")

    # Setup signal handlers for graceful shutdown
    shutdown_requested = threading.Event()
    termination_triggered = threading.Event()

    signal_pipe_r, signal_pipe_w = os.pipe()
    os.set_blocking(signal_pipe_r, False)
    os.set_blocking(signal_pipe_w, False)
    previous_wakeup_fd = signal.set_wakeup_fd(signal_pipe_w)

    def trigger_shutdown(reason: str):
        if not shutdown_requested.is_set():
            logger.info(reason)
            shutdown_requested.set()
        if termination_triggered.is_set():
            return
        termination_triggered.set()
        app.performSelectorOnMainThread_withObject_waitUntilDone_(
            'terminate:', None, False
        )

    def signal_handler(signum, frame):
        trigger_shutdown(f"Received interrupt signal ({signum}), shutting down...")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create a background thread that monitors for shutdown requests.
    # NSApplication.run() blocks Python's normal signal processing, so we watch a wakeup fd instead.
    def shutdown_monitor():
        while not termination_triggered.is_set():
            if shutdown_requested.is_set():
                trigger_shutdown("Processing shutdown request...")
                break

            ready, _, _ = select.select([signal_pipe_r], [], [], 0.1)
            if not ready:
                continue

            try:
                # Drain the pipe; contents are irrelevant, presence means a signal fired.
                os.read(signal_pipe_r, 1024)
            except BlockingIOError:
                pass

            trigger_shutdown("Processing shutdown request...")
            break

    monitor_thread = threading.Thread(target=shutdown_monitor, daemon=True)
    monitor_thread.start()

    try:
        app.run()
    finally:
        logger.info("Cleaning up resources...")
        shutdown_requested.set()
        termination_triggered.set()
        signal.set_wakeup_fd(previous_wakeup_fd)
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=1)
        os.close(signal_pipe_r)
        os.close(signal_pipe_w)

        # Cancel async tasks and shutdown orchestrator
        if press_handler_task:
            press_handler_task.cancel()
        orchestrator.shutdown()
        icon_controller.shutdown()

        # Stop the event loop
        loop.call_soon_threadsafe(loop.stop)
        if loop_thread.is_alive():
            loop_thread.join(timeout=2)
        loop.close()

        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
