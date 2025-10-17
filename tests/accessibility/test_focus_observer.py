"""Unit tests for the FocusObserver module."""

import asyncio
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

# Mock the PyObjC modules before importing the module under test
sys.modules['Quartz'] = MagicMock()
sys.modules['ApplicationServices'] = MagicMock()
sys.modules['objc'] = MagicMock()

# Setup mock constants
sys.modules['ApplicationServices'].AXUIElementCreateSystemWide = MagicMock()
sys.modules['ApplicationServices'].AXUIElementCopyAttributeValue = MagicMock()
sys.modules['ApplicationServices'].kAXFocusedUIElementAttribute = "AXFocusedUIElement"
sys.modules['ApplicationServices'].kAXFocusedApplicationAttribute = "AXFocusedApplication"
sys.modules['ApplicationServices'].kAXBundleIdentifierAttribute = "AXBundleIdentifier"
sys.modules['ApplicationServices'].kAXRoleAttribute = "AXRole"
sys.modules['ApplicationServices'].kAXSubroleAttribute = "AXSubrole"
sys.modules['Quartz'].AXIsProcessTrustedWithOptions = MagicMock()
sys.modules['Quartz'].kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"

from src.whisper_input_mac.accessibility import (
    FocusObserver,
    FocusedElementInfo,
    AccessibilityPermissionError,
    wait_for_trusted_access,
)


class TestFocusedElementInfo:
    """Tests for FocusedElementInfo dataclass."""

    def test_normalize_value_with_string(self):
        """Test that string values are returned as-is."""
        assert FocusedElementInfo._normalize_value("test") == "test"

    def test_normalize_value_with_none(self):
        """Test that None values are returned as None."""
        assert FocusedElementInfo._normalize_value(None) is None

    def test_normalize_value_with_int(self):
        """Test that non-string values are converted to string."""
        assert FocusedElementInfo._normalize_value(42) == "42"

    def test_normalize_value_with_exception(self):
        """Test that exceptions during conversion return None."""
        mock_obj = Mock()
        mock_obj.__str__ = Mock(side_effect=Exception("Test error"))
        assert FocusedElementInfo._normalize_value(mock_obj) is None

    def test_dataclass_creation(self):
        """Test creating FocusedElementInfo with all fields."""
        info = FocusedElementInfo(
            bundle_identifier="com.apple.Terminal",
            role="AXTextField",
            subrole="AXSearchField"
        )
        assert info.bundle_identifier == "com.apple.Terminal"
        assert info.role == "AXTextField"
        assert info.subrole == "AXSearchField"

    def test_dataclass_default_values(self):
        """Test that FocusedElementInfo has None default values."""
        info = FocusedElementInfo()
        assert info.bundle_identifier is None
        assert info.role is None
        assert info.subrole is None


class TestFocusObserver:
    """Tests for FocusObserver class."""

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    def test_init_success(self, mock_create_system_wide):
        """Test successful initialization of FocusObserver."""
        mock_system_wide = Mock()
        mock_create_system_wide.return_value = mock_system_wide

        observer = FocusObserver()

        assert observer._system_wide == mock_system_wide
        mock_create_system_wide.assert_called_once()

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    def test_init_failure(self, mock_create_system_wide):
        """Test initialization failure raises exception."""
        mock_create_system_wide.side_effect = Exception("Init failed")

        with pytest.raises(Exception, match="Init failed"):
            FocusObserver()

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_ensure_trusted_returns_true(self, mock_is_trusted, mock_create_system_wide):
        """Test ensure_trusted returns True when process is trusted."""
        mock_create_system_wide.return_value = Mock()
        mock_is_trusted.return_value = True

        observer = FocusObserver()
        result = observer.ensure_trusted(prompt=True)

        assert result is True
        mock_is_trusted.assert_called_once()

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_ensure_trusted_returns_false(self, mock_is_trusted, mock_create_system_wide):
        """Test ensure_trusted returns False when process is not trusted."""
        mock_create_system_wide.return_value = Mock()
        mock_is_trusted.return_value = False

        observer = FocusObserver()
        result = observer.ensure_trusted(prompt=False)

        assert result is False

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_ensure_trusted_with_objc_error(self, mock_is_trusted, mock_create_system_wide):
        """Test ensure_trusted raises AccessibilityPermissionError on objc.error."""
        mock_create_system_wide.return_value = Mock()

        # Mock objc.error
        with patch("src.whisper_input_mac.accessibility.focus_observer.objc") as mock_objc:
            mock_objc.error = Exception
            mock_is_trusted.side_effect = Exception("PyObjC error")

            observer = FocusObserver()

            with pytest.raises(AccessibilityPermissionError, match="Failed to check accessibility trust"):
                observer.ensure_trusted()

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCopyAttributeValue")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_get_focused_element_success(
        self, mock_is_trusted, mock_copy_attr, mock_create_system_wide
    ):
        """Test successful retrieval of focused element info."""
        mock_create_system_wide.return_value = Mock()
        mock_is_trusted.return_value = True

        # Mock focused element and application
        mock_focused_element = Mock()
        mock_focused_app = Mock()

        # Setup mock return values for attribute queries
        def copy_attr_side_effect(element, attr_key, none_val):
            if attr_key == "AXFocusedUIElement":
                return (mock_focused_element, None)
            elif attr_key == "AXFocusedApplication":
                return (mock_focused_app, None)
            elif attr_key == "AXBundleIdentifier":
                return ("com.apple.Terminal", None)
            elif attr_key == "AXRole":
                return ("AXTextField", None)
            elif attr_key == "AXSubrole":
                return ("AXSearchField", None)
            return (None, "error")

        # Patch the constants
        with patch.multiple(
            "src.whisper_input_mac.accessibility.focus_observer",
            kAXFocusedUIElementAttribute="AXFocusedUIElement",
            kAXFocusedApplicationAttribute="AXFocusedApplication",
            kAXBundleIdentifierAttribute="AXBundleIdentifier",
            kAXRoleAttribute="AXRole",
            kAXSubroleAttribute="AXSubrole",
        ):
            mock_copy_attr.side_effect = copy_attr_side_effect

            observer = FocusObserver()
            info = observer.get_focused_element()

            assert info is not None
            assert info.bundle_identifier == "com.apple.Terminal"
            assert info.role == "AXTextField"
            assert info.subrole == "AXSearchField"

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_get_focused_element_not_trusted(self, mock_is_trusted, mock_create_system_wide):
        """Test get_focused_element raises error when not trusted."""
        mock_create_system_wide.return_value = Mock()
        mock_is_trusted.return_value = False

        observer = FocusObserver()

        with pytest.raises(AccessibilityPermissionError, match="Accessibility permission not granted"):
            observer.get_focused_element()

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCopyAttributeValue")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_get_focused_element_no_focus(
        self, mock_is_trusted, mock_copy_attr, mock_create_system_wide
    ):
        """Test get_focused_element returns None when no element is focused."""
        mock_create_system_wide.return_value = Mock()
        mock_is_trusted.return_value = True

        # Return error when getting focused element
        mock_copy_attr.return_value = (None, "error")

        with patch(
            "src.whisper_input_mac.accessibility.focus_observer.kAXFocusedUIElementAttribute",
            "AXFocusedUIElement"
        ):
            observer = FocusObserver()
            info = observer.get_focused_element()

            assert info is None

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCopyAttributeValue")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXIsProcessTrustedWithOptions")
    def test_get_focused_element_with_objc_error(
        self, mock_is_trusted, mock_copy_attr, mock_create_system_wide
    ):
        """Test get_focused_element handles objc.error gracefully."""
        mock_create_system_wide.return_value = Mock()
        mock_is_trusted.return_value = True

        with patch("src.whisper_input_mac.accessibility.focus_observer.objc") as mock_objc:
            mock_objc.error = Exception
            mock_copy_attr.side_effect = Exception("PyObjC error")

            with patch(
                "src.whisper_input_mac.accessibility.focus_observer.kAXFocusedUIElementAttribute",
                "AXFocusedUIElement"
            ):
                observer = FocusObserver()

                with pytest.raises(AccessibilityPermissionError, match="Failed to get focused element"):
                    observer.get_focused_element()

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCopyAttributeValue")
    def test_get_attribute_success(self, mock_copy_attr, mock_create_system_wide):
        """Test _get_attribute returns value successfully."""
        mock_create_system_wide.return_value = Mock()
        mock_copy_attr.return_value = ("test_value", None)

        mock_element = Mock()
        result = FocusObserver._get_attribute(mock_element, "test_key")

        assert result == "test_value"

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCopyAttributeValue")
    def test_get_attribute_with_error(self, mock_copy_attr, mock_create_system_wide):
        """Test _get_attribute returns None on error."""
        mock_create_system_wide.return_value = Mock()
        mock_copy_attr.return_value = (None, "error")

        mock_element = Mock()
        result = FocusObserver._get_attribute(mock_element, "test_key")

        assert result is None

    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCreateSystemWide")
    @patch("src.whisper_input_mac.accessibility.focus_observer.AXUIElementCopyAttributeValue")
    def test_get_attribute_with_exception(self, mock_copy_attr, mock_create_system_wide):
        """Test _get_attribute returns None on exception."""
        mock_create_system_wide.return_value = Mock()
        mock_copy_attr.side_effect = Exception("Test error")

        mock_element = Mock()
        result = FocusObserver._get_attribute(mock_element, "test_key")

        assert result is None


class TestWaitForTrustedAccess:
    """Tests for wait_for_trusted_access async function."""

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_immediate_success(self, mock_focus_observer_class):
        """Test wait_for_trusted_access returns True when already trusted."""
        mock_observer = Mock()
        mock_observer.ensure_trusted = Mock(return_value=True)
        mock_focus_observer_class.return_value = mock_observer

        result = await wait_for_trusted_access(
            focus_observer=mock_observer,
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is True
        mock_observer.ensure_trusted.assert_called()

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_timeout(self, mock_focus_observer_class):
        """Test wait_for_trusted_access returns False on timeout."""
        mock_observer = Mock()
        mock_observer.ensure_trusted = Mock(return_value=False)
        mock_focus_observer_class.return_value = mock_observer

        result = await wait_for_trusted_access(
            focus_observer=mock_observer,
            timeout=0.5,
            poll_interval=0.1
        )

        assert result is False

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_eventually_succeeds(self, mock_focus_observer_class):
        """Test wait_for_trusted_access returns True when permission granted during wait."""
        mock_observer = Mock()

        # Simulate permission granted after 2 calls
        call_count = [0]
        def ensure_trusted_side_effect(prompt):
            call_count[0] += 1
            return call_count[0] >= 2

        mock_observer.ensure_trusted = Mock(side_effect=ensure_trusted_side_effect)
        mock_focus_observer_class.return_value = mock_observer

        result = await wait_for_trusted_access(
            focus_observer=mock_observer,
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is True
        assert call_count[0] >= 2

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_creates_observer(self, mock_focus_observer_class):
        """Test wait_for_trusted_access creates observer when none provided."""
        mock_observer = Mock()
        mock_observer.ensure_trusted = Mock(return_value=True)
        mock_focus_observer_class.return_value = mock_observer

        result = await wait_for_trusted_access(
            focus_observer=None,
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is True
        mock_focus_observer_class.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_creation_failure(self, mock_focus_observer_class):
        """Test wait_for_trusted_access raises error when observer creation fails."""
        mock_focus_observer_class.side_effect = Exception("Creation failed")

        with pytest.raises(AccessibilityPermissionError, match="Failed to create FocusObserver"):
            await wait_for_trusted_access(
                focus_observer=None,
                timeout=5.0,
                poll_interval=0.1
            )

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_handles_permission_error(self, mock_focus_observer_class):
        """Test wait_for_trusted_access handles AccessibilityPermissionError during polling."""
        mock_observer = Mock()

        # Raise error first, then succeed
        call_count = [0]
        def ensure_trusted_side_effect(prompt):
            call_count[0] += 1
            if call_count[0] < 2:
                raise AccessibilityPermissionError("Not trusted yet")
            return True

        mock_observer.ensure_trusted = Mock(side_effect=ensure_trusted_side_effect)
        mock_focus_observer_class.return_value = mock_observer

        result = await wait_for_trusted_access(
            focus_observer=mock_observer,
            timeout=5.0,
            poll_interval=0.1
        )

        assert result is True

    @pytest.mark.asyncio
    @patch("src.whisper_input_mac.accessibility.focus_observer.FocusObserver")
    async def test_wait_for_trusted_access_cancellation(self, mock_focus_observer_class):
        """Test wait_for_trusted_access handles cancellation properly."""
        mock_observer = Mock()
        mock_observer.ensure_trusted = Mock(return_value=False)
        mock_focus_observer_class.return_value = mock_observer

        task = asyncio.create_task(wait_for_trusted_access(
            focus_observer=mock_observer,
            timeout=10.0,
            poll_interval=0.1
        ))

        # Give it a moment to start
        await asyncio.sleep(0.05)

        # Cancel the task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
