"""Preferences storage and management."""

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class PreferenceKey(str, Enum):
    """Enumeration of preference keys."""
    HOTKEY_KEYCODE = "hotkey_keycode"
    HOTKEY_MODIFIERS = "hotkey_modifiers"
    AUTO_PUNCTUATION = "auto_punctuation"
    LANGUAGE = "language"
    MICROPHONE_STATE = "microphone_state"
    ACCESSIBILITY_STATE = "accessibility_state"


@dataclass
class HotkeyConfig:
    """Configuration for global hotkey."""
    keycode: int  # Carbon key code
    modifiers: int  # Carbon modifier flags

    @staticmethod
    def default() -> "HotkeyConfig":
        """Return default hotkey config (Space key, no modifiers)."""
        return HotkeyConfig(keycode=49, modifiers=0)


@dataclass
class PreferencesSchema:
    """Schema for preferences with validation and defaults."""

    # Hotkey configuration
    hotkey_keycode: int = 49  # Space key
    hotkey_modifiers: int = 0  # No modifiers

    # Transcription settings
    auto_punctuation: bool = True
    language: str = "en"  # ISO 639-1 language code

    # Permission states (for tracking)
    microphone_state: str = "pending"  # pending, granted, denied
    accessibility_state: str = "pending"  # pending, granted, denied

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "PreferencesSchema":
        """Create from dictionary with validation."""
        return PreferencesSchema(
            hotkey_keycode=data.get("hotkey_keycode", 49),
            hotkey_modifiers=data.get("hotkey_modifiers", 0),
            auto_punctuation=data.get("auto_punctuation", True),
            language=data.get("language", "en"),
            microphone_state=data.get("microphone_state", "pending"),
            accessibility_state=data.get("accessibility_state", "pending"),
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        Validate preferences.

        Returns:
            (is_valid, error_message)
        """
        # Validate hotkey_keycode
        if not isinstance(self.hotkey_keycode, int) or self.hotkey_keycode < 0:
            return False, f"Invalid hotkey_keycode: {self.hotkey_keycode}"

        # Validate hotkey_modifiers
        if not isinstance(self.hotkey_modifiers, int) or self.hotkey_modifiers < 0:
            return False, f"Invalid hotkey_modifiers: {self.hotkey_modifiers}"

        # Validate auto_punctuation
        if not isinstance(self.auto_punctuation, bool):
            return False, f"Invalid auto_punctuation: {self.auto_punctuation}"

        # Validate language
        if not isinstance(self.language, str) or len(self.language) < 2:
            return False, f"Invalid language: {self.language}"

        # Validate permission states
        valid_states = {"pending", "granted", "denied"}
        if self.microphone_state not in valid_states:
            return False, f"Invalid microphone_state: {self.microphone_state}"
        if self.accessibility_state not in valid_states:
            return False, f"Invalid accessibility_state: {self.accessibility_state}"

        return True, None


class PreferencesStore:
    """
    Manages preference persistence and change notifications.

    Preferences are stored in a JSON file and loaded/saved with schema validation.
    Change listeners can be registered to receive updates when preferences change.
    """

    def __init__(self, preferences_path: Optional[Path] = None):
        """
        Initialize preferences store.

        Args:
            preferences_path: Path to preferences.json file.
                            Defaults to ~/.whisper-input-mac/preferences.json
        """
        if preferences_path is None:
            preferences_dir = Path.home() / ".whisper-input-mac"
            preferences_dir.mkdir(parents=True, exist_ok=True)
            preferences_path = preferences_dir / "preferences.json"

        self.preferences_path = preferences_path
        self._prefs: PreferencesSchema = PreferencesSchema()
        self._change_listeners: list[Callable[[PreferenceKey, Any], None]] = []

        # Load preferences from disk
        self.load()

    def load(self) -> bool:
        """
        Load preferences from disk.

        Returns:
            True if loaded successfully, False if file doesn't exist or is invalid
        """
        if not self.preferences_path.exists():
            logger.info(f"Preferences file not found, using defaults: {self.preferences_path}")
            self._prefs = PreferencesSchema()
            # Save defaults to disk
            self.save()
            return False

        try:
            with open(self.preferences_path, 'r') as f:
                data = json.load(f)

            self._prefs = PreferencesSchema.from_dict(data)

            # Validate loaded preferences
            is_valid, error = self._prefs.validate()
            if not is_valid:
                logger.error(f"Invalid preferences loaded: {error}. Using defaults.")
                self._prefs = PreferencesSchema()
                return False

            logger.info(f"Preferences loaded from {self.preferences_path}")
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse preferences JSON: {e}. Using defaults.")
            self._prefs = PreferencesSchema()
            return False
        except Exception as e:
            logger.error(f"Failed to load preferences: {e}. Using defaults.")
            self._prefs = PreferencesSchema()
            return False

    def save(self) -> bool:
        """
        Save preferences to disk.

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Validate before saving
            is_valid, error = self._prefs.validate()
            if not is_valid:
                logger.error(f"Cannot save invalid preferences: {error}")
                return False

            # Ensure directory exists
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to file
            with open(self.preferences_path, 'w') as f:
                json.dump(self._prefs.to_dict(), f, indent=2)

            logger.debug(f"Preferences saved to {self.preferences_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
            return False

    def get(self, key: PreferenceKey) -> Any:
        """
        Get a preference value.

        Args:
            key: Preference key to retrieve

        Returns:
            The preference value
        """
        return getattr(self._prefs, key.value)

    def set(self, key: PreferenceKey, value: Any, save: bool = True) -> bool:
        """
        Set a preference value.

        Args:
            key: Preference key to set
            value: New value
            save: If True, immediately save to disk (default: True)

        Returns:
            True if set successfully, False otherwise
        """
        try:
            # Set the value
            old_value = getattr(self._prefs, key.value)
            setattr(self._prefs, key.value, value)

            # Validate
            is_valid, error = self._prefs.validate()
            if not is_valid:
                logger.error(f"Invalid preference value: {error}. Reverting.")
                setattr(self._prefs, key.value, old_value)
                return False

            # Save if requested
            if save:
                if not self.save():
                    logger.error("Failed to save preferences after setting value")
                    setattr(self._prefs, key.value, old_value)
                    return False

            # Notify listeners
            self._notify_listeners(key, value)

            logger.debug(f"Preference updated: {key.value} = {value}")
            return True

        except Exception as e:
            logger.error(f"Failed to set preference {key.value}: {e}")
            return False

    def get_hotkey_config(self) -> HotkeyConfig:
        """Get current hotkey configuration."""
        return HotkeyConfig(
            keycode=self._prefs.hotkey_keycode,
            modifiers=self._prefs.hotkey_modifiers
        )

    def set_hotkey_config(self, config: HotkeyConfig, save: bool = True) -> bool:
        """
        Set hotkey configuration.

        Args:
            config: New hotkey configuration
            save: If True, immediately save to disk (default: True)

        Returns:
            True if set successfully, False otherwise
        """
        try:
            old_keycode = self._prefs.hotkey_keycode
            old_modifiers = self._prefs.hotkey_modifiers

            self._prefs.hotkey_keycode = config.keycode
            self._prefs.hotkey_modifiers = config.modifiers

            # Validate
            is_valid, error = self._prefs.validate()
            if not is_valid:
                logger.error(f"Invalid hotkey config: {error}. Reverting.")
                self._prefs.hotkey_keycode = old_keycode
                self._prefs.hotkey_modifiers = old_modifiers
                return False

            # Save if requested
            if save:
                if not self.save():
                    logger.error("Failed to save preferences after setting hotkey")
                    self._prefs.hotkey_keycode = old_keycode
                    self._prefs.hotkey_modifiers = old_modifiers
                    return False

            # Notify listeners
            self._notify_listeners(PreferenceKey.HOTKEY_KEYCODE, config.keycode)
            self._notify_listeners(PreferenceKey.HOTKEY_MODIFIERS, config.modifiers)

            logger.info(f"Hotkey config updated: keycode={config.keycode}, modifiers={config.modifiers}")
            return True

        except Exception as e:
            logger.error(f"Failed to set hotkey config: {e}")
            return False

    def add_change_listener(self, listener: Callable[[PreferenceKey, Any], None]) -> None:
        """
        Add a change listener.

        Args:
            listener: Callback function(key, new_value) to be called on preference changes
        """
        if listener not in self._change_listeners:
            self._change_listeners.append(listener)
            logger.debug(f"Change listener added: {listener}")

    def remove_change_listener(self, listener: Callable[[PreferenceKey, Any], None]) -> None:
        """
        Remove a change listener.

        Args:
            listener: Callback function to remove
        """
        if listener in self._change_listeners:
            self._change_listeners.remove(listener)
            logger.debug(f"Change listener removed: {listener}")

    def _notify_listeners(self, key: PreferenceKey, new_value: Any) -> None:
        """
        Notify all change listeners.

        Args:
            key: The preference key that changed
            new_value: The new value
        """
        for listener in self._change_listeners:
            try:
                listener(key, new_value)
            except Exception as e:
                logger.error(f"Error in preference change listener: {e}")

    def reset_to_defaults(self, save: bool = True) -> bool:
        """
        Reset all preferences to default values.

        Args:
            save: If True, immediately save to disk (default: True)

        Returns:
            True if reset successfully, False otherwise
        """
        try:
            self._prefs = PreferencesSchema()

            if save:
                if not self.save():
                    logger.error("Failed to save after reset")
                    return False

            # Notify all listeners of changes
            for key in PreferenceKey:
                self._notify_listeners(key, getattr(self._prefs, key.value))

            logger.info("Preferences reset to defaults")
            return True

        except Exception as e:
            logger.error(f"Failed to reset preferences: {e}")
            return False

    @property
    def schema(self) -> PreferencesSchema:
        """Get the current preferences schema (read-only)."""
        return self._prefs
