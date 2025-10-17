import asyncio
import logging
from enum import Enum
from typing import Optional, Callable

from Cocoa import (
    NSStatusBar,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSProgressIndicator,
    NSView,
    NSRect,
)

from .icon_utils import create_idle_icon, create_recording_icon, create_busy_icon
from .press_hold_detector import PressHoldDetector

logger = logging.getLogger(__name__)


class IconState(Enum):
    """Enum for status icon states."""
    IDLE = "idle"
    RECORDING = "recording"
    BUSY = "busy"


class StatusIconController:
    """Controller managing status bar icon and state transitions."""

    def __init__(self, enable_press_hold: bool = True, enable_hotkey: bool = False):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.current_state = IconState.IDLE
        self._spinner_view: Optional[NSView] = None
        self._spinner: Optional[NSProgressIndicator] = None
        self._debounce_task: Optional[asyncio.Task] = None
        self._debounce_delay = 0.1

        # Press lifecycle event queue for downstream consumers (lazy-initialized)
        self._press_events: Optional[asyncio.Queue] = None

        # Cache icons
        self.icons = {
            IconState.IDLE: create_idle_icon(),
            IconState.RECORDING: create_recording_icon(),
            IconState.BUSY: create_busy_icon(),
        }

        # Press-hold detection
        self._press_hold_detector: Optional[PressHoldDetector] = None
        self._enable_press_hold = enable_press_hold
        self._enable_hotkey = enable_hotkey

        self._setup_menu()
        self._set_state_immediate(IconState.IDLE)

        # Start press-hold detection if enabled
        if self._enable_press_hold:
            self._setup_press_hold_detector()

    def _setup_press_hold_detector(self):
        """Setup press-hold detection on the status button."""
        try:
            button = self.status_item.button()
            if button is None:
                logger.warning("Status button is None, skipping press-hold detection setup")
                return
            
            self._press_hold_detector = PressHoldDetector(button, hold_threshold=0.35)
            
            # Wire callbacks
            self._press_hold_detector.on_press_start = self._on_press_start
            self._press_hold_detector.on_hold_threshold = self._on_hold_threshold
            self._press_hold_detector.on_press_end = self._on_press_end
            
            self._press_hold_detector.start()
            logger.debug("Press-hold detector initialized")
        except Exception as e:
            logger.warning(f"Failed to setup press-hold detector: {e}")

    @property
    def press_events(self) -> asyncio.Queue:
        """Get the press events queue, lazily initializing it if needed."""
        if self._press_events is None:
            try:
                self._press_events = asyncio.Queue()
            except RuntimeError:
                # No event loop, create a dummy queue-like object
                logger.warning("No event loop available for press_events queue")
                self._press_events = asyncio.Queue()
        return self._press_events

    async def _emit_press_event(self, event_type: str):
        """Emit a press lifecycle event to the event queue."""
        try:
            await self.press_events.put({"type": event_type})
            logger.debug(f"Emitted press event: {event_type}")
        except Exception as e:
            logger.warning(f"Failed to emit press event: {e}")

    def _on_press_start(self):
        """Handle press start event."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit_press_event("press_started"))
        except RuntimeError:
            logger.warning("No running loop for press_started event")

    def _on_hold_threshold(self):
        """Handle hold threshold reached event."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit_press_event("hold_started"))
        except RuntimeError:
            logger.warning("No running loop for hold_started event")
        
        self.enter_recording()

    def _on_press_end(self):
        """Handle press end event."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._emit_press_event("press_released"))
        except RuntimeError:
            logger.warning("No running loop for press_released event")
        
        self.exit_recording()

    def _setup_menu(self):
        """Setup menu for status item."""
        menu = NSMenu.alloc().init()
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Whisper Input", "terminate:", "q"
        )
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    def _set_state_immediate(self, state: IconState):
        """Immediately update icon and tooltip without debouncing."""
        self.current_state = state
        button = self.status_item.button()

        if state == IconState.BUSY:
            self._start_spinner()
        else:
            self._stop_spinner()

        # Update icon
        button.setImage_(self.icons[state])

        # Update tooltip
        tooltips = {
            IconState.IDLE: "Whisper Input - Ready",
            IconState.RECORDING: "Whisper Input - Recording",
            IconState.BUSY: "Whisper Input - Transcribing",
        }
        button.setToolTip_(tooltips[state])

        logger.debug(f"State changed to {state.value}")

    def _start_spinner(self):
        """Start animated spinner in the status item button."""
        if self._spinner is not None:
            return

        button = self.status_item.button()
        button_frame = button.frame()

        # Create container view for spinner
        self._spinner_view = NSView.alloc().initWithFrame_(button_frame)

        # Create progress indicator (spinner)
        spinner_size = button_frame.size.height - 4
        spinner_rect = NSRect(
            (2, (button_frame.size.height - spinner_size) / 2),
            (spinner_size, spinner_size),
        )
        self._spinner = NSProgressIndicator.alloc().initWithFrame_(spinner_rect)
        self._spinner.setIndeterminate_(True)
        self._spinner.startAnimation_(None)

        self._spinner_view.addSubview_(self._spinner)
        button.addSubview_(self._spinner_view)
        logger.debug("Started spinner")

    def _stop_spinner(self):
        """Stop and remove animated spinner."""
        if self._spinner is None:
            return

        self._spinner.stopAnimation_(None)
        self._spinner_view.removeFromSuperview()
        self._spinner = None
        self._spinner_view = None
        logger.debug("Stopped spinner")

    async def _debounced_set_state(self, state: IconState):
        """Set state with debouncing to prevent flicker on rapid transitions."""
        # Cancel previous debounce task if any
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()

        # Create new debounce task
        async def delayed_set():
            await asyncio.sleep(self._debounce_delay)
            self._set_state_immediate(state)

        self._debounce_task = asyncio.create_task(delayed_set())

    def set_state(self, state: IconState):
        """
        Set the icon state. Debounces to prevent flicker on rapid transitions.
        Can be called sync or within an event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._debounced_set_state(state))
        except RuntimeError:
            # No running event loop, set immediately
            self._set_state_immediate(state)

    def enter_recording(self):
        """Enter recording state."""
        self.set_state(IconState.RECORDING)
        logger.info("Entered recording state")

    def exit_recording(self):
        """Exit recording state back to idle."""
        self.set_state(IconState.IDLE)
        logger.info("Exited recording state")

    def set_busy(self):
        """Set busy state for transcription."""
        self.set_state(IconState.BUSY)
        logger.info("Set to busy state")

    def set_idle(self):
        """Set idle state."""
        self.set_state(IconState.IDLE)
        logger.info("Set to idle state")

    def shutdown(self):
        """Clean up resources."""
        if self._press_hold_detector is not None:
            self._press_hold_detector.stop()
            logger.debug("Press-hold detector stopped")

    @property
    def status_button(self):
        """Get the status bar button."""
        return self.status_item.button()

    def __del__(self):
        """Cleanup on deletion."""
        self.shutdown()
