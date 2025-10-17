"""Tests for press_hold_detector module."""

import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock
from Cocoa import NSApplication, NSApplicationActivationPolicyAccessory

from whisper_input_mac.press_hold_detector import PressHoldDetector


@pytest.fixture(scope="session", autouse=True)
def setup_app():
    """Setup NSApplication for macOS API calls."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    yield


@pytest.fixture
def mock_button():
    """Create a mock button."""
    button = MagicMock()
    button.window.return_value = MagicMock()
    button.frame.return_value = MagicMock(origin=MagicMock(x=0, y=0),
                                          size=MagicMock(width=50, height=50))
    return button


class TestPressHoldDetectorInitialization:
    """Test PressHoldDetector initialization."""

    def test_detector_initializes(self, mock_button):
        """Test detector initializes with correct default state."""
        detector = PressHoldDetector(mock_button)

        assert detector.button is mock_button
        assert detector.hold_threshold == 0.35
        assert detector._hold_task is None
        assert detector._is_pressed is False
        assert detector.on_press_start is None
        assert detector.on_hold_threshold is None
        assert detector.on_press_end is None

    def test_detector_custom_threshold(self, mock_button):
        """Test detector accepts custom hold threshold."""
        detector = PressHoldDetector(mock_button, hold_threshold=0.5)

        assert detector.hold_threshold == 0.5


class TestPressHoldDetectorCallbacks:
    """Test callback registration and invocation."""

    def test_callback_registration(self, mock_button):
        """Test callbacks can be registered."""
        detector = PressHoldDetector(mock_button)
        
        callback_start = MagicMock()
        callback_hold = MagicMock()
        callback_end = MagicMock()

        detector.on_press_start = callback_start
        detector.on_hold_threshold = callback_hold
        detector.on_press_end = callback_end

        assert detector.on_press_start is callback_start
        assert detector.on_hold_threshold is callback_hold
        assert detector.on_press_end is callback_end


class TestPressHoldDetectorStartStop:
    """Test start/stop monitoring."""

    def test_start_monitoring(self, mock_button):
        """Test start method registers monitors."""
        detector = PressHoldDetector(mock_button)
        
        with patch('whisper_input_mac.press_hold_detector.NSEvent') as mock_ns_event:
            detector.start()
            
            # Verify monitors were registered
            assert mock_ns_event.addLocalMonitorForEventsMatchingMask_handler_.call_count == 2

    def test_stop_monitoring(self, mock_button):
        """Test stop method removes monitors."""
        detector = PressHoldDetector(mock_button)
        
        with patch('whisper_input_mac.press_hold_detector.NSEvent') as mock_ns_event:
            detector.start()
            detector.stop()
            
            # Verify monitors were removed
            assert mock_ns_event.removeMonitor_.call_count == 2

    def test_stop_without_start(self, mock_button):
        """Test stop can be called without start."""
        detector = PressHoldDetector(mock_button)
        
        # Should not raise an error
        detector.stop()


class TestPressHoldDetectorAsync:
    """Test async hold timing."""

    @pytest.mark.asyncio
    async def test_hold_fires_after_threshold(self, mock_button):
        """Test hold callback fires after threshold time."""
        detector = PressHoldDetector(mock_button, hold_threshold=0.05)
        
        callback_hold = MagicMock()
        detector.on_hold_threshold = callback_hold

        # Create and run hold task manually
        task = asyncio.create_task(detector._fire_hold())
        await asyncio.sleep(0.1)
        
        assert callback_hold.called

    @pytest.mark.asyncio
    async def test_hold_cancelled_before_threshold(self, mock_button):
        """Test hold can be cancelled before threshold."""
        detector = PressHoldDetector(mock_button, hold_threshold=0.1)
        
        callback_hold = MagicMock()
        detector.on_hold_threshold = callback_hold

        # Create hold task and cancel it quickly
        task = asyncio.create_task(detector._fire_hold())
        await asyncio.sleep(0.02)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Callback should not be called
        assert not callback_hold.called


class TestPressHoldDetectorButtonClickDetection:
    """Test button click detection."""

    def test_is_button_clicked_returns_bool(self, mock_button):
        """Test _is_button_clicked returns boolean."""
        detector = PressHoldDetector(mock_button)
        
        event = MagicMock()
        event.window.return_value = mock_button.window.return_value
        event.locationInWindow.return_value = MagicMock(x=25, y=25)

        result = detector._is_button_clicked(event)
        assert isinstance(result, bool)

    def test_is_button_clicked_no_window(self, mock_button):
        """Test _is_button_clicked with no window."""
        detector = PressHoldDetector(mock_button)
        
        event = MagicMock()
        event.window.return_value = None

        result = detector._is_button_clicked(event)
        assert result is False


class TestPressHoldDetectorCleanup:
    """Test cleanup on deletion."""

    def test_cleanup_on_deletion(self, mock_button):
        """Test detector cleans up on deletion."""
        detector = PressHoldDetector(mock_button)
        
        with patch.object(detector, 'stop') as mock_stop:
            detector.__del__()
            mock_stop.assert_called_once()
