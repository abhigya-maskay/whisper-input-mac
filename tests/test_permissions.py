"""Unit tests for permissions module."""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile
import json

from whisper_input_mac.permissions import (
    PermissionsCoordinator,
    PermissionState,
    PermissionStatus,
)
from whisper_input_mac.preferences import PreferencesStore, PreferenceKey


@pytest.fixture
def temp_preferences_file():
    """Create a temporary preferences file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)
        prefs_data = {
            "hotkey_keycode": 101,
            "hotkey_modifiers": 0,
            "auto_punctuation": True,
            "language": "en",
            "microphone_state": "pending",
            "accessibility_state": "pending",
        }
        json.dump(prefs_data, f)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def preferences_store(temp_preferences_file):
    """Create a PreferencesStore with a temporary file."""
    return PreferencesStore(preferences_path=temp_preferences_file)


@pytest.fixture
def permissions_coordinator(preferences_store):
    """Create a PermissionsCoordinator instance."""
    return PermissionsCoordinator(
        preferences_store=preferences_store,
        on_state_change=None,
    )


def test_permission_status_initialization(permissions_coordinator):
    """Test that PermissionsCoordinator initializes with correct state."""
    status = permissions_coordinator.get_status()

    assert status.microphone == PermissionState.PENDING
    assert status.accessibility == PermissionState.PENDING


def test_permission_status_all_granted():
    """Test PermissionStatus.all_granted() method."""
    status_granted = PermissionStatus(
        microphone=PermissionState.GRANTED,
        accessibility=PermissionState.GRANTED,
    )
    assert status_granted.all_granted() is True

    status_denied = PermissionStatus(
        microphone=PermissionState.DENIED,
        accessibility=PermissionState.GRANTED,
    )
    assert status_denied.all_granted() is False


def test_permission_status_to_dict():
    """Test PermissionStatus.to_dict() method."""
    status = PermissionStatus(
        microphone=PermissionState.GRANTED,
        accessibility=PermissionState.DENIED,
    )
    result = status.to_dict()

    assert result == {
        "microphone": "granted",
        "accessibility": "denied",
    }


@pytest.mark.asyncio
@patch('whisper_input_mac.permissions.AVAudioSession')
async def test_check_microphone_permission_granted(mock_audio_session, permissions_coordinator):
    """Test checking microphone permission when granted."""
    # Mock AVAudioSession to grant permission
    mock_session = Mock()
    mock_audio_session.sharedInstance.return_value = mock_session

    def mock_request_permission(handler):
        handler(True)  # Grant permission

    mock_session.requestRecordPermission_ = mock_request_permission

    # Check permission
    state = await permissions_coordinator.check_microphone_permission(request_if_needed=True)

    assert state == PermissionState.GRANTED
    assert permissions_coordinator.get_status().microphone == PermissionState.GRANTED


@pytest.mark.asyncio
@patch('whisper_input_mac.permissions.AVAudioSession')
async def test_check_microphone_permission_denied(mock_audio_session, permissions_coordinator):
    """Test checking microphone permission when denied."""
    # Mock AVAudioSession to deny permission
    mock_session = Mock()
    mock_audio_session.sharedInstance.return_value = mock_session

    def mock_request_permission(handler):
        handler(False)  # Deny permission

    mock_session.requestRecordPermission_ = mock_request_permission

    # Check permission
    state = await permissions_coordinator.check_microphone_permission(request_if_needed=True)

    assert state == PermissionState.DENIED
    assert permissions_coordinator.get_status().microphone == PermissionState.DENIED


@patch('whisper_input_mac.permissions.AXIsProcessTrustedWithOptions')
def test_check_accessibility_permission_granted(mock_ax_trusted, permissions_coordinator):
    """Test checking accessibility permission when granted."""
    # Mock accessibility check to return True
    mock_ax_trusted.return_value = True

    state = permissions_coordinator.check_accessibility_permission(prompt=False)

    assert state == PermissionState.GRANTED
    assert permissions_coordinator.get_status().accessibility == PermissionState.GRANTED


@patch('whisper_input_mac.permissions.AXIsProcessTrustedWithOptions')
def test_check_accessibility_permission_denied(mock_ax_trusted, permissions_coordinator):
    """Test checking accessibility permission when denied."""
    # Mock accessibility check to return False
    mock_ax_trusted.return_value = False

    state = permissions_coordinator.check_accessibility_permission(prompt=False)

    assert state == PermissionState.DENIED
    assert permissions_coordinator.get_status().accessibility == PermissionState.DENIED


def test_state_change_callback(preferences_store):
    """Test that state change callback is invoked."""
    callback_invoked = []

    def on_state_change(status):
        callback_invoked.append(status)

    coordinator = PermissionsCoordinator(
        preferences_store=preferences_store,
        on_state_change=on_state_change,
    )

    # Manually update state (simulating a permission check)
    with patch('whisper_input_mac.permissions.AXIsProcessTrustedWithOptions', return_value=True):
        coordinator.check_accessibility_permission(prompt=False)

    # Verify callback was invoked
    assert len(callback_invoked) == 1
    assert callback_invoked[0].accessibility == PermissionState.GRANTED


def test_permission_state_persistence(preferences_store):
    """Test that permission states are persisted to preferences."""
    coordinator = PermissionsCoordinator(
        preferences_store=preferences_store,
        on_state_change=None,
    )

    # Update microphone state
    with patch('whisper_input_mac.permissions.AVAudioSession'):
        coordinator._update_microphone_state(PermissionState.GRANTED)

    # Verify it was persisted
    saved_state = preferences_store.get(PreferenceKey.MICROPHONE_STATE)
    assert saved_state == "granted"


@pytest.mark.asyncio
@patch('whisper_input_mac.permissions.AXIsProcessTrustedWithOptions')
async def test_wait_for_accessibility_permission_timeout(mock_ax_trusted, permissions_coordinator):
    """Test waiting for accessibility permission times out."""
    # Mock accessibility to always return False
    mock_ax_trusted.return_value = False

    # Wait with very short timeout
    state = await permissions_coordinator.wait_for_accessibility_permission(
        prompt=False,
        timeout=0.5,
        poll_interval=0.1,
    )

    assert state == PermissionState.DENIED


@pytest.mark.asyncio
@patch('whisper_input_mac.permissions.AXIsProcessTrustedWithOptions')
@patch('whisper_input_mac.permissions.AVAudioSession')
async def test_ensure_ready_all_granted(mock_audio_session, mock_ax_trusted, permissions_coordinator):
    """Test ensure_ready when all permissions are granted."""
    # Mock microphone permission
    mock_session = Mock()
    mock_audio_session.sharedInstance.return_value = mock_session

    def mock_request_permission(handler):
        handler(True)

    mock_session.requestRecordPermission_ = mock_request_permission

    # Mock accessibility permission
    mock_ax_trusted.return_value = True

    # Ensure ready
    status = await permissions_coordinator.ensure_ready(show_dialogs=False)

    assert status.all_granted() is True


@pytest.mark.asyncio
@patch('whisper_input_mac.permissions.AVAudioSession')
async def test_ensure_ready_microphone_denied_raises(mock_audio_session, permissions_coordinator):
    """Test ensure_ready raises when microphone is denied."""
    # Mock microphone permission denial
    mock_session = Mock()
    mock_audio_session.sharedInstance.return_value = mock_session

    def mock_request_permission(handler):
        handler(False)  # Deny

    mock_session.requestRecordPermission_ = mock_request_permission

    # Ensure ready should raise
    with pytest.raises(PermissionError, match="Microphone permission denied"):
        await permissions_coordinator.ensure_ready(show_dialogs=False)
