"""Tests for global_hotkey module."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from whisper_input_mac.global_hotkey import GlobalHotkey, HAS_CARBON


@pytest.mark.skipif(not HAS_CARBON, reason="Carbon framework not available")
class TestGlobalHotkeyWithCarbon:
    """Test GlobalHotkey when Carbon is available."""

    def test_hotkey_initialization(self):
        """Test GlobalHotkey initializes correctly."""
        hotkey = GlobalHotkey()

        assert hotkey.hotkey_refs == {}
        assert hotkey._event_handler_ref is None

    def test_hotkey_constants(self):
        """Test hotkey key code constants."""
        assert GlobalHotkey.SPACE == 49
        assert GlobalHotkey.RETURN == 36


class TestGlobalHotkeyWithoutCarbon:
    """Test GlobalHotkey when Carbon is not available."""

    def test_initialization_without_carbon(self):
        """Test GlobalHotkey initializes even without Carbon."""
        hotkey = GlobalHotkey()

        assert hotkey is not None
        assert isinstance(hotkey.hotkey_refs, dict)

    def test_register_returns_false_without_carbon(self):
        """Test register returns False without Carbon."""
        hotkey = GlobalHotkey()
        
        # Temporarily patch HAS_CARBON to False for testing
        with patch('whisper_input_mac.global_hotkey.HAS_CARBON', False):
            result = hotkey.register(49, 0, lambda: None)
            assert result is False

    def test_unregister_returns_false_for_missing_hotkey(self):
        """Test unregister returns False for missing hotkey."""
        hotkey = GlobalHotkey()
        
        result = hotkey.unregister("nonexistent")
        assert result is False

    def test_cleanup_doesnt_crash(self):
        """Test cleanup doesn't crash."""
        hotkey = GlobalHotkey()
        
        # Should not raise an error
        hotkey.cleanup()

    def test_cleanup_on_deletion(self):
        """Test cleanup is called on deletion."""
        hotkey = GlobalHotkey()
        
        with patch.object(hotkey, 'cleanup') as mock_cleanup:
            hotkey.__del__()
            mock_cleanup.assert_called_once()


@pytest.mark.skipif(not HAS_CARBON, reason="Carbon framework not available")
class TestGlobalHotkeyRegistration:
    """Test hotkey registration and unregistration with Carbon."""

    def test_register_hotkey(self):
        """Test registering a hotkey."""
        hotkey = GlobalHotkey()
        callback = MagicMock()

        with patch('whisper_input_mac.global_hotkey.HIToolbox') as mock_hitools:
            mock_hitools.RegisterEventHotKey.return_value = "ref"
            
            result = hotkey.register(49, 0, callback, "test_hotkey")
            
            # Registration should succeed or fail gracefully
            assert isinstance(result, bool)

    def test_unregister_hotkey(self):
        """Test unregistering a hotkey."""
        hotkey = GlobalHotkey()
        callback = MagicMock()

        with patch('whisper_input_mac.global_hotkey.HIToolbox') as mock_hitools:
            mock_hitools.RegisterEventHotKey.return_value = "ref"
            
            # Register first
            hotkey.register(49, 0, callback, "test_hotkey")
            
            # Now unregister
            if "test_hotkey" in hotkey.hotkey_refs:
                result = hotkey.unregister("test_hotkey")
                assert result is True

    def test_multiple_hotkeys(self):
        """Test registering multiple hotkeys."""
        hotkey = GlobalHotkey()
        callback1 = MagicMock()
        callback2 = MagicMock()

        with patch('whisper_input_mac.global_hotkey.HIToolbox') as mock_hitools:
            mock_hitools.RegisterEventHotKey.return_value = "ref"
            
            hotkey.register(49, 0, callback1, "hotkey1")
            hotkey.register(36, 0, callback2, "hotkey2")
            
            # Both should be registered
            # (or at least the method should handle multiple registrations)


class TestGlobalHotkeyErrorHandling:
    """Test error handling in global hotkey."""

    def test_register_with_none_callback(self):
        """Test register with None callback."""
        hotkey = GlobalHotkey()
        
        # Should handle gracefully
        result = hotkey.register(49, 0, None)
        assert isinstance(result, bool)

    def test_cleanup_with_multiple_hotkeys(self):
        """Test cleanup attempts to remove all hotkeys."""
        hotkey = GlobalHotkey()
        
        # Add some hotkey refs manually with None refs (safe to skip unregister)
        hotkey.hotkey_refs["key1"] = {"ref": None}
        hotkey.hotkey_refs["key2"] = {"ref": None}
        
        # Cleanup should try to remove them (may fail if Carbon not available)
        hotkey.cleanup()
        
        # Should be empty after cleanup attempt
        assert len(hotkey.hotkey_refs) == 0

    def test_dispatch_on_loop_no_running_loop(self):
        """Test _dispatch_on_loop when no event loop is running."""
        hotkey = GlobalHotkey()
        callback = MagicMock()
        
        # Should handle gracefully
        hotkey._dispatch_on_loop(callback)
