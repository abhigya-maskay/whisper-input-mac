"""Unit tests for the text injection module."""

import sys
import pytest
from unittest.mock import Mock, patch, MagicMock, call

# Mock the PyObjC modules before importing the module under test
sys.modules['Quartz'] = MagicMock()
sys.modules['Cocoa'] = MagicMock()
sys.modules['objc'] = MagicMock()

# Setup mock constants and functions for Quartz
sys.modules['Quartz'].AXIsProcessTrustedWithOptions = MagicMock()
sys.modules['Quartz'].kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"
sys.modules['Quartz'].CGEventCreateKeyboardEvent = MagicMock()
sys.modules['Quartz'].CGEventKeyboardSetUnicodeString = MagicMock()
sys.modules['Quartz'].CGEventPost = MagicMock()
sys.modules['Quartz'].kCGHIDEventTap = "kCGHIDEventTap"
sys.modules['Quartz'].kCGEventKeyDown = "kCGEventKeyDown"
sys.modules['Quartz'].kCGEventKeyUp = "kCGEventKeyUp"

# Setup mock constants and classes for Cocoa
sys.modules['Cocoa'].NSPasteboard = MagicMock()
sys.modules['Cocoa'].NSStringPboardType = "NSStringPboardType"
sys.modules['Cocoa'].NSString = MagicMock()

from src.whisper_input_mac.text_injector import (
    TextInjectionError,
    KeyboardInjector,
    ClipboardFallback,
    TextInjector,
)


class TestTextInjectionError:
    """Tests for TextInjectionError exception."""

    def test_exception_creation(self):
        """Test that TextInjectionError can be created and raised."""
        error = TextInjectionError("Test error")
        assert str(error) == "Test error"

    def test_exception_inheritance(self):
        """Test that TextInjectionError inherits from Exception."""
        assert issubclass(TextInjectionError, Exception)


class TestKeyboardInjector:
    """Tests for KeyboardInjector class."""

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_ensure_trusted_access_returns_true(self, mock_is_trusted):
        """Test ensure_trusted_access returns True when process is trusted."""
        mock_is_trusted.return_value = True

        injector = KeyboardInjector()
        result = injector.ensure_trusted_access(prompt=True)

        assert result is True
        mock_is_trusted.assert_called_once()

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_ensure_trusted_access_returns_false(self, mock_is_trusted):
        """Test ensure_trusted_access returns False when not trusted."""
        mock_is_trusted.return_value = False

        injector = KeyboardInjector()
        result = injector.ensure_trusted_access(prompt=False)

        assert result is False

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_ensure_trusted_access_with_objc_error(self, mock_is_trusted):
        """Test ensure_trusted_access raises TextInjectionError on objc.error."""
        with patch("src.whisper_input_mac.text_injector.objc") as mock_objc:
            mock_objc.error = Exception
            mock_is_trusted.side_effect = Exception("PyObjC error")

            injector = KeyboardInjector()

            with pytest.raises(TextInjectionError, match="Failed to check accessibility trust"):
                injector.ensure_trusted_access()

    @patch("src.whisper_input_mac.text_injector.CGEventPost")
    @patch("src.whisper_input_mac.text_injector.CGEventKeyboardSetUnicodeString")
    @patch("src.whisper_input_mac.text_injector.CGEventCreateKeyboardEvent")
    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_send_unicode_success(
        self, mock_is_trusted, mock_create_event, mock_set_unicode, mock_post_event
    ):
        """Test send_unicode successfully injects text."""
        mock_is_trusted.return_value = True
        mock_key_down = Mock()
        mock_key_up = Mock()
        mock_create_event.side_effect = [mock_key_down, mock_key_up]

        injector = KeyboardInjector()
        injector.send_unicode("Hello")

        # Verify events were created
        assert mock_create_event.call_count == 2
        mock_create_event.assert_any_call(None, 0, True)
        mock_create_event.assert_any_call(None, 0, False)

        # Verify Unicode string was set on both events
        assert mock_set_unicode.call_count == 2
        mock_set_unicode.assert_any_call(mock_key_down, 5, "Hello")
        mock_set_unicode.assert_any_call(mock_key_up, 5, "Hello")

        # Verify events were posted
        assert mock_post_event.call_count == 2

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_send_unicode_empty_text(self, mock_is_trusted):
        """Test send_unicode raises error for empty text."""
        injector = KeyboardInjector()

        with pytest.raises(TextInjectionError, match="Cannot inject empty text"):
            injector.send_unicode("")

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_send_unicode_not_trusted(self, mock_is_trusted):
        """Test send_unicode raises error when not trusted."""
        mock_is_trusted.return_value = False

        injector = KeyboardInjector()

        with pytest.raises(TextInjectionError, match="Accessibility permission not granted"):
            injector.send_unicode("Hello")

    @patch("src.whisper_input_mac.text_injector.CGEventCreateKeyboardEvent")
    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_send_unicode_event_creation_failure(
        self, mock_is_trusted, mock_create_event
    ):
        """Test send_unicode handles event creation failure."""
        mock_is_trusted.return_value = True
        mock_create_event.return_value = None

        injector = KeyboardInjector()

        with pytest.raises(TextInjectionError, match="Failed to create keyboard events"):
            injector.send_unicode("Hello")

    @patch("src.whisper_input_mac.text_injector.CGEventPost")
    @patch("src.whisper_input_mac.text_injector.CGEventKeyboardSetUnicodeString")
    @patch("src.whisper_input_mac.text_injector.CGEventCreateKeyboardEvent")
    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    def test_send_unicode_with_objc_error(
        self, mock_is_trusted, mock_create_event, mock_set_unicode, mock_post_event
    ):
        """Test send_unicode handles PyObjC errors gracefully."""
        mock_is_trusted.return_value = True
        mock_create_event.return_value = Mock()

        with patch("src.whisper_input_mac.text_injector.objc") as mock_objc:
            mock_objc.error = Exception
            mock_set_unicode.side_effect = Exception("PyObjC error")

            injector = KeyboardInjector()

            with pytest.raises(TextInjectionError, match="Keystroke injection failed"):
                injector.send_unicode("Hello")


class TestClipboardFallback:
    """Tests for ClipboardFallback class."""

    def test_init_default_restore(self):
        """Test ClipboardFallback initializes with default restore_clipboard=True."""
        fallback = ClipboardFallback()
        assert fallback.restore_clipboard is True

    def test_init_custom_restore(self):
        """Test ClipboardFallback can be initialized with custom restore_clipboard."""
        fallback = ClipboardFallback(restore_clipboard=False)
        assert fallback.restore_clipboard is False

    def test_paste_text_empty_string(self):
        """Test paste_text returns False for empty string."""
        fallback = ClipboardFallback()
        result = fallback.paste_text("")
        assert result is False

    @patch("src.whisper_input_mac.text_injector.CGEventPost")
    @patch("src.whisper_input_mac.text_injector.CGEventCreateKeyboardEvent")
    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    @patch("src.whisper_input_mac.text_injector.NSString")
    @patch("src.whisper_input_mac.text_injector.NSPasteboard")
    def test_paste_text_success(
        self, mock_pasteboard_class, mock_nsstring, mock_is_trusted,
        mock_create_event, mock_post_event
    ):
        """Test paste_text successfully pastes text."""
        # Setup mocks
        mock_pasteboard = Mock()
        mock_pasteboard_class.generalPasteboard.return_value = mock_pasteboard
        mock_pasteboard.stringForType_.return_value = "previous"
        mock_pasteboard.setString_forType_.return_value = True

        mock_ns_string = Mock()
        mock_nsstring.stringWithString_.return_value = mock_ns_string

        mock_is_trusted.return_value = True
        mock_create_event.return_value = Mock()

        # Test
        fallback = ClipboardFallback(restore_clipboard=True)
        result = fallback.paste_text("Hello World")

        # Verify
        assert result is True
        mock_pasteboard.clearContents.assert_called()
        mock_nsstring.stringWithString_.assert_called_with("Hello World")
        mock_pasteboard.setString_forType_.assert_called()

        # Verify Cmd+V simulation (4 events: Cmd down, V down, V up, Cmd up)
        assert mock_create_event.call_count == 4
        assert mock_post_event.call_count == 4

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    @patch("src.whisper_input_mac.text_injector.NSString")
    @patch("src.whisper_input_mac.text_injector.NSPasteboard")
    def test_paste_text_clipboard_write_failure(
        self, mock_pasteboard_class, mock_nsstring, mock_is_trusted
    ):
        """Test paste_text returns False when clipboard write fails."""
        mock_pasteboard = Mock()
        mock_pasteboard_class.generalPasteboard.return_value = mock_pasteboard
        mock_pasteboard.setString_forType_.return_value = False

        mock_ns_string = Mock()
        mock_nsstring.stringWithString_.return_value = mock_ns_string

        fallback = ClipboardFallback()
        result = fallback.paste_text("Hello")

        assert result is False

    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    @patch("src.whisper_input_mac.text_injector.NSString")
    @patch("src.whisper_input_mac.text_injector.NSPasteboard")
    def test_paste_text_without_accessibility(
        self, mock_pasteboard_class, mock_nsstring, mock_is_trusted
    ):
        """Test paste_text succeeds partially without accessibility (clipboard set)."""
        mock_pasteboard = Mock()
        mock_pasteboard_class.generalPasteboard.return_value = mock_pasteboard
        mock_pasteboard.setString_forType_.return_value = True

        mock_ns_string = Mock()
        mock_nsstring.stringWithString_.return_value = mock_ns_string

        mock_is_trusted.return_value = False  # No accessibility permission

        fallback = ClipboardFallback()
        result = fallback.paste_text("Hello")

        # Should return True even without accessibility (clipboard is set)
        assert result is True

    @patch("src.whisper_input_mac.text_injector.CGEventPost")
    @patch("src.whisper_input_mac.text_injector.CGEventCreateKeyboardEvent")
    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    @patch("src.whisper_input_mac.text_injector.NSString")
    @patch("src.whisper_input_mac.text_injector.NSPasteboard")
    def test_paste_text_restores_clipboard(
        self, mock_pasteboard_class, mock_nsstring, mock_is_trusted,
        mock_create_event, mock_post_event
    ):
        """Test paste_text restores previous clipboard contents."""
        mock_pasteboard = Mock()
        mock_pasteboard_class.generalPasteboard.return_value = mock_pasteboard
        mock_pasteboard.stringForType_.return_value = "previous content"
        mock_pasteboard.setString_forType_.return_value = True

        mock_nsstring.stringWithString_.return_value = Mock()
        mock_is_trusted.return_value = True
        mock_create_event.return_value = Mock()

        fallback = ClipboardFallback(restore_clipboard=True)
        result = fallback.paste_text("New text")

        assert result is True

        # Verify clipboard was cleared and set twice (once for new text, once for restore)
        assert mock_pasteboard.clearContents.call_count == 2
        assert mock_pasteboard.setString_forType_.call_count == 2

    @patch("src.whisper_input_mac.text_injector.CGEventPost")
    @patch("src.whisper_input_mac.text_injector.CGEventCreateKeyboardEvent")
    @patch("src.whisper_input_mac.text_injector.AXIsProcessTrustedWithOptions")
    @patch("src.whisper_input_mac.text_injector.NSString")
    @patch("src.whisper_input_mac.text_injector.NSPasteboard")
    def test_paste_text_no_restore(
        self, mock_pasteboard_class, mock_nsstring, mock_is_trusted,
        mock_create_event, mock_post_event
    ):
        """Test paste_text doesn't restore clipboard when disabled."""
        mock_pasteboard = Mock()
        mock_pasteboard_class.generalPasteboard.return_value = mock_pasteboard
        mock_pasteboard.stringForType_.return_value = "previous content"
        mock_pasteboard.setString_forType_.return_value = True

        mock_nsstring.stringWithString_.return_value = Mock()
        mock_is_trusted.return_value = True
        mock_create_event.return_value = Mock()

        fallback = ClipboardFallback(restore_clipboard=False)
        result = fallback.paste_text("New text")

        assert result is True

        # Verify clipboard was only cleared once (no restoration)
        assert mock_pasteboard.clearContents.call_count == 1
        assert mock_pasteboard.setString_forType_.call_count == 1


class TestTextInjector:
    """Tests for TextInjector facade class."""

    def test_init_default_restore(self):
        """Test TextInjector initializes with default restore_clipboard=True."""
        injector = TextInjector()
        assert injector.clipboard_fallback.restore_clipboard is True

    def test_init_custom_restore(self):
        """Test TextInjector can be initialized with custom restore_clipboard."""
        injector = TextInjector(restore_clipboard=False)
        assert injector.clipboard_fallback.restore_clipboard is False

    def test_send_text_empty_string(self):
        """Test send_text returns error for empty string."""
        injector = TextInjector()
        success, error = injector.send_text("")

        assert success is False
        assert error == "Cannot inject empty text"

    @patch.object(KeyboardInjector, "send_unicode")
    def test_send_text_keystroke_success(self, mock_send_unicode):
        """Test send_text uses keystroke injection when successful."""
        mock_send_unicode.return_value = None

        injector = TextInjector()
        success, error = injector.send_text("Hello")

        assert success is True
        assert error is None
        mock_send_unicode.assert_called_once_with("Hello")

    @patch.object(ClipboardFallback, "paste_text")
    @patch.object(KeyboardInjector, "send_unicode")
    def test_send_text_fallback_to_clipboard(self, mock_send_unicode, mock_paste_text):
        """Test send_text falls back to clipboard on keystroke failure."""
        mock_send_unicode.side_effect = TextInjectionError("Injection failed")
        mock_paste_text.return_value = True

        injector = TextInjector()
        success, error = injector.send_text("Hello")

        assert success is True
        assert error is None
        mock_send_unicode.assert_called_once_with("Hello")
        mock_paste_text.assert_called_once_with("Hello")

    @patch.object(ClipboardFallback, "paste_text")
    @patch.object(KeyboardInjector, "send_unicode")
    def test_send_text_both_methods_fail(self, mock_send_unicode, mock_paste_text):
        """Test send_text returns error when both methods fail."""
        mock_send_unicode.side_effect = TextInjectionError("Injection failed")
        mock_paste_text.return_value = False

        injector = TextInjector()
        success, error = injector.send_text("Hello")

        assert success is False
        assert error == "Both keystroke injection and clipboard fallback failed"

    @patch.object(ClipboardFallback, "paste_text")
    @patch.object(KeyboardInjector, "send_unicode")
    def test_send_text_prefer_clipboard(self, mock_send_unicode, mock_paste_text):
        """Test send_text uses clipboard directly when preferred."""
        mock_paste_text.return_value = True

        injector = TextInjector()
        success, error = injector.send_text("Hello", prefer_clipboard=True)

        assert success is True
        assert error is None
        mock_paste_text.assert_called_once_with("Hello")
        mock_send_unicode.assert_not_called()

    @patch.object(ClipboardFallback, "paste_text")
    @patch.object(KeyboardInjector, "send_unicode")
    def test_send_text_prefer_clipboard_failure(self, mock_send_unicode, mock_paste_text):
        """Test send_text returns error when preferred clipboard fails."""
        mock_paste_text.return_value = False

        injector = TextInjector()
        success, error = injector.send_text("Hello", prefer_clipboard=True)

        assert success is False
        assert error == "Clipboard paste failed"
        mock_send_unicode.assert_not_called()
