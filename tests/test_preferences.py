"""Unit tests for preferences module."""

import pytest
import json
import tempfile
from pathlib import Path

from whisper_input_mac.preferences import (
    PreferencesStore,
    PreferencesSchema,
    PreferenceKey,
    HotkeyConfig,
)


@pytest.fixture
def temp_preferences_file():
    """Create a temporary preferences file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)
        # Write default preferences
        prefs_data = {
            "hotkey_keycode": 49,
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


def test_preferences_schema_defaults():
    """Test that PreferencesSchema has correct defaults."""
    schema = PreferencesSchema()

    assert schema.hotkey_keycode == 49  # Space key
    assert schema.hotkey_modifiers == 0
    assert schema.auto_punctuation is True
    assert schema.language == "en"
    assert schema.microphone_state == "pending"
    assert schema.accessibility_state == "pending"


def test_preferences_schema_to_dict():
    """Test PreferencesSchema.to_dict()."""
    schema = PreferencesSchema(
        hotkey_keycode=36,
        hotkey_modifiers=256,
        auto_punctuation=False,
    )

    result = schema.to_dict()

    assert result["hotkey_keycode"] == 36
    assert result["hotkey_modifiers"] == 256
    assert result["auto_punctuation"] is False


def test_preferences_schema_from_dict():
    """Test PreferencesSchema.from_dict()."""
    data = {
        "hotkey_keycode": 36,
        "hotkey_modifiers": 256,
        "auto_punctuation": False,
        "language": "es",
        "microphone_state": "granted",
        "accessibility_state": "denied",
    }

    schema = PreferencesSchema.from_dict(data)

    assert schema.hotkey_keycode == 36
    assert schema.hotkey_modifiers == 256
    assert schema.auto_punctuation is False
    assert schema.language == "es"
    assert schema.microphone_state == "granted"
    assert schema.accessibility_state == "denied"


def test_preferences_schema_from_dict_partial():
    """Test PreferencesSchema.from_dict() with partial data uses defaults."""
    data = {
        "hotkey_keycode": 36,
    }

    schema = PreferencesSchema.from_dict(data)

    assert schema.hotkey_keycode == 36
    assert schema.hotkey_modifiers == 0  # Default
    assert schema.auto_punctuation is True  # Default


def test_preferences_schema_validate_valid():
    """Test PreferencesSchema.validate() with valid data."""
    schema = PreferencesSchema()
    is_valid, error = schema.validate()

    assert is_valid is True
    assert error is None


def test_preferences_schema_validate_invalid_keycode():
    """Test PreferencesSchema.validate() with invalid keycode."""
    schema = PreferencesSchema(hotkey_keycode=-1)
    is_valid, error = schema.validate()

    assert is_valid is False
    assert "keycode" in error


def test_preferences_schema_validate_invalid_state():
    """Test PreferencesSchema.validate() with invalid permission state."""
    schema = PreferencesSchema(microphone_state="invalid_state")
    is_valid, error = schema.validate()

    assert is_valid is False
    assert "microphone_state" in error


def test_preferences_store_init_creates_file(temp_preferences_file):
    """Test that PreferencesStore creates file with defaults if missing."""
    # Delete the temp file so store creates it
    if temp_preferences_file.exists():
        temp_preferences_file.unlink()

    store = PreferencesStore(preferences_path=temp_preferences_file)

    assert temp_preferences_file.exists()
    assert store.schema.hotkey_keycode == 49


def test_preferences_store_load_existing(temp_preferences_file):
    """Test that PreferencesStore loads existing preferences."""
    # Write test data
    test_data = {
        "hotkey_keycode": 36,
        "hotkey_modifiers": 256,
        "auto_punctuation": False,
        "language": "fr",
        "microphone_state": "granted",
        "accessibility_state": "granted",
    }

    with open(temp_preferences_file, 'w') as f:
        json.dump(test_data, f)

    store = PreferencesStore(preferences_path=temp_preferences_file)

    assert store.schema.hotkey_keycode == 36
    assert store.schema.hotkey_modifiers == 256
    assert store.schema.auto_punctuation is False
    assert store.schema.language == "fr"


def test_preferences_store_get(temp_preferences_file):
    """Test PreferencesStore.get()."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    hotkey_keycode = store.get(PreferenceKey.HOTKEY_KEYCODE)
    auto_punct = store.get(PreferenceKey.AUTO_PUNCTUATION)

    assert hotkey_keycode == 49
    assert auto_punct is True


def test_preferences_store_set(temp_preferences_file):
    """Test PreferencesStore.set()."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    success = store.set(PreferenceKey.AUTO_PUNCTUATION, False, save=True)

    assert success is True
    assert store.get(PreferenceKey.AUTO_PUNCTUATION) is False

    # Verify it was saved to disk
    with open(temp_preferences_file, 'r') as f:
        data = json.load(f)
        assert data["auto_punctuation"] is False


def test_preferences_store_set_invalid_value(temp_preferences_file):
    """Test PreferencesStore.set() with invalid value."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    # Try to set invalid keycode
    success = store.set(PreferenceKey.HOTKEY_KEYCODE, -1, save=True)

    assert success is False
    assert store.get(PreferenceKey.HOTKEY_KEYCODE) == 49  # Unchanged


def test_preferences_store_get_hotkey_config(temp_preferences_file):
    """Test PreferencesStore.get_hotkey_config()."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    config = store.get_hotkey_config()

    assert isinstance(config, HotkeyConfig)
    assert config.keycode == 49
    assert config.modifiers == 0


def test_preferences_store_set_hotkey_config(temp_preferences_file):
    """Test PreferencesStore.set_hotkey_config()."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    new_config = HotkeyConfig(keycode=36, modifiers=256)
    success = store.set_hotkey_config(new_config, save=True)

    assert success is True
    assert store.get(PreferenceKey.HOTKEY_KEYCODE) == 36
    assert store.get(PreferenceKey.HOTKEY_MODIFIERS) == 256


def test_preferences_store_change_listener(temp_preferences_file):
    """Test PreferencesStore change listeners."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    changes_received = []

    def listener(key, value):
        changes_received.append((key, value))

    store.add_change_listener(listener)

    # Make a change
    store.set(PreferenceKey.AUTO_PUNCTUATION, False, save=True)

    # Verify listener was called
    assert len(changes_received) == 1
    assert changes_received[0] == (PreferenceKey.AUTO_PUNCTUATION, False)


def test_preferences_store_remove_listener(temp_preferences_file):
    """Test PreferencesStore.remove_change_listener()."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    changes_received = []

    def listener(key, value):
        changes_received.append((key, value))

    store.add_change_listener(listener)
    store.set(PreferenceKey.AUTO_PUNCTUATION, False, save=True)

    assert len(changes_received) == 1

    # Remove listener and make another change
    store.remove_change_listener(listener)
    store.set(PreferenceKey.HOTKEY_KEYCODE, 36, save=True)

    # Should still be 1 (listener wasn't called for second change)
    assert len(changes_received) == 1


def test_preferences_store_reset_to_defaults(temp_preferences_file):
    """Test PreferencesStore.reset_to_defaults()."""
    store = PreferencesStore(preferences_path=temp_preferences_file)

    # Make some changes
    store.set(PreferenceKey.AUTO_PUNCTUATION, False, save=True)
    store.set(PreferenceKey.HOTKEY_KEYCODE, 36, save=True)

    # Reset to defaults
    success = store.reset_to_defaults(save=True)

    assert success is True
    assert store.get(PreferenceKey.AUTO_PUNCTUATION) is True
    assert store.get(PreferenceKey.HOTKEY_KEYCODE) == 49


def test_hotkey_config_default():
    """Test HotkeyConfig.default()."""
    config = HotkeyConfig.default()

    assert config.keycode == 49
    assert config.modifiers == 0


def test_preferences_store_load_invalid_json(temp_preferences_file):
    """Test PreferencesStore handles invalid JSON gracefully."""
    # Write invalid JSON
    with open(temp_preferences_file, 'w') as f:
        f.write("{invalid json}")

    store = PreferencesStore(preferences_path=temp_preferences_file)

    # Should fall back to defaults
    assert store.schema.hotkey_keycode == 49
    assert store.schema.auto_punctuation is True
