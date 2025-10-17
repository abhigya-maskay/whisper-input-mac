import asyncio
import logging
from typing import Callable, Optional

from Cocoa import NSEvent, NSEventMaskLeftMouseDown, NSEventMaskLeftMouseUp

logger = logging.getLogger(__name__)


class PressHoldDetector:
    """Detects press-and-hold events on a button, differentiating tap vs hold."""

    def __init__(self, button, hold_threshold: float = 0.35):
        """
        Initialize the detector.

        Args:
            button: The NSButton to monitor
            hold_threshold: Time in seconds before hold is triggered
        """
        self.button = button
        self.hold_threshold = hold_threshold
        self._hold_task: Optional[asyncio.Task] = None
        self._is_pressed = False

        # Callbacks
        self.on_press_start: Optional[Callable] = None
        self.on_hold_threshold: Optional[Callable] = None
        self.on_press_end: Optional[Callable] = None

        self._monitor_down = None
        self._monitor_up = None

    def start(self):
        """Start monitoring for mouse events on the button."""
        self._monitor_down = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskLeftMouseDown, self._handle_mouse_down
        )
        self._monitor_up = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskLeftMouseUp, self._handle_mouse_up
        )
        logger.debug("PressHoldDetector started")

    def stop(self):
        """Stop monitoring for mouse events."""
        if self._monitor_down is not None:
            monitor = self._monitor_down
            try:
                NSEvent.removeMonitor_(monitor)
            except (ValueError, AttributeError, TypeError) as exc:
                logger.debug("Failed to remove down monitor cleanly: %s", exc)
            finally:
                self._monitor_down = None
        if self._monitor_up is not None:
            monitor = self._monitor_up
            try:
                NSEvent.removeMonitor_(monitor)
            except (ValueError, AttributeError, TypeError) as exc:
                logger.debug("Failed to remove up monitor cleanly: %s", exc)
            finally:
                self._monitor_up = None
        logger.debug("PressHoldDetector stopped")

    def _handle_mouse_down(self, event):
        """Handle mouse down event."""
        if self._is_button_clicked(event):
            self._is_pressed = True
            self._invoke_callback(self.on_press_start)
            
            try:
                loop = asyncio.get_running_loop()
                self._hold_task = loop.create_task(self._fire_hold())
            except RuntimeError:
                logger.warning("No running event loop for hold detection")
        
        return event

    def _handle_mouse_up(self, event):
        """Handle mouse up event."""
        if self._is_pressed:
            self._is_pressed = False
            
            # Cancel hold task if it hasn't fired yet
            if self._hold_task is not None and not self._hold_task.done():
                self._hold_task.cancel()
                self._hold_task = None
            
            self._invoke_callback(self.on_press_end)
        
        return event

    def _is_button_clicked(self, event) -> bool:
        """Check if the event is on the monitored button."""
        event_window = event.window()
        button_window = self.button.window()
        
        if not event_window or not button_window:
            return False
        
        # Check if the event is in the button's coordinate space
        button_frame = self.button.frame()
        event_location = event.locationInWindow()
        
        # Convert to button's coordinate system
        if event_location.x >= button_frame.origin.x and \
           event_location.x <= button_frame.origin.x + button_frame.size.width and \
           event_location.y >= button_frame.origin.y and \
           event_location.y <= button_frame.origin.y + button_frame.size.height:
            return True
        
        return False

    def _invoke_callback(self, callback: Optional[Callable]) -> None:
        """
        Invoke a callback, using loop.call_soon_threadsafe if a loop is running.
        
        Args:
            callback: The callback to invoke, or None
        """
        if not callback:
            return
        
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(callback)
        except RuntimeError:
            callback()

    async def _fire_hold(self):
        """Wait for hold threshold and fire callback if not cancelled."""
        try:
            await asyncio.sleep(self.hold_threshold)
            self._invoke_callback(self.on_hold_threshold)
            logger.debug("Hold threshold reached")
        except asyncio.CancelledError:
            logger.debug("Hold cancelled (tap detected)")

    def __del__(self):
        """Cleanup on deletion."""
        self.stop()
