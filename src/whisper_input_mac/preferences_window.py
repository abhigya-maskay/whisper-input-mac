"""Native Cocoa preferences window for Whisper Input."""

import logging
from typing import Optional, Callable

from Cocoa import (
    NSWindow,
    NSWindowController,
    NSPanel,
    NSView,
    NSButton,
    NSTextField,
    NSTextAlignment,
    NSCenterTextAlignment,
    NSFont,
    NSRect,
    NSMakeRect,
    NSBezelBorder,
    NSEvent,
    NSKeyDown,
    NSKeyDownMask,
    NSFlagsChangedMask,
    NSCommandKeyMask,
    NSShiftKeyMask,
    NSAlternateKeyMask,
    NSControlKeyMask,
    NSApplication,
    NSPopUpButton,
    NSMenu,
    NSMenuItem,
    NSObject,
)
import objc

from .preferences import PreferencesStore, PreferenceKey, HotkeyConfig

logger = logging.getLogger(__name__)

# Supported languages for Whisper transcription
SUPPORTED_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
}


class PreferencesWindowController(NSObject):
    """Controller for the native preferences window."""

    def init(self):
        """Initialize as NSObject."""
        self = objc.super(PreferencesWindowController, self).init()
        if self is None:
            return None

        # Instance variables
        self.preferences = None
        self.on_apply = None
        self.window = None

        # UI elements
        self.hotkey_field = None
        self.auto_punctuation_checkbox = None
        self.language_popup = None

        # Temporary hotkey state (while recording)
        self._recording_hotkey = False
        self._temp_hotkey_keycode = None
        self._temp_hotkey_modifiers = None
        self._event_monitor = None

        return self

    def initWithPreferencesStore_onApply_(
        self,
        preferences_store: PreferencesStore,
        on_apply: Optional[Callable[[HotkeyConfig, bool, str], None]],
    ):
        """
        Initialize the preferences window controller.

        Args:
            preferences_store: PreferencesStore instance
            on_apply: Callback(hotkey_config, auto_punctuation, language) when Apply is clicked
        """
        self = self.init()
        if self is None:
            return None

        self.preferences = preferences_store
        self.on_apply = on_apply

        return self

    def show(self) -> None:
        """Show the preferences window."""
        if self.window is None:
            self._create_window()

        # Load current preferences
        self._load_preferences()

        # Show window
        self.window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        logger.info("Preferences window shown")

    def _create_window(self) -> None:
        """Create the preferences window."""
        # Create window (taller to fit language dropdown)
        window_rect = NSMakeRect(0, 0, 450, 300)
        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            window_rect,
            (1 << 0) | (1 << 1) | (1 << 3),  # NSTitledWindowMask | NSClosableWindowMask | NSResizableWindowMask
            2,  # NSBackingStoreBuffered
            False,
        )
        self.window.setTitle_("Whisper Input Preferences")
        self.window.center()

        # Content view
        content_view = self.window.contentView()

        # Title label
        title_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 250, 410, 30))
        title_label.setStringValue_("Preferences")
        title_label.setBezeled_(False)
        title_label.setDrawsBackground_(False)
        title_label.setEditable_(False)
        title_label.setSelectable_(False)
        title_label.setFont_(NSFont.boldSystemFontOfSize_(18))
        content_view.addSubview_(title_label)

        # Hotkey section
        hotkey_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 210, 150, 20))
        hotkey_label.setStringValue_("Global Hotkey:")
        hotkey_label.setBezeled_(False)
        hotkey_label.setDrawsBackground_(False)
        hotkey_label.setEditable_(False)
        hotkey_label.setSelectable_(False)
        content_view.addSubview_(hotkey_label)

        self.hotkey_field = NSTextField.alloc().initWithFrame_(NSMakeRect(170, 205, 180, 30))
        self.hotkey_field.setEditable_(False)
        self.hotkey_field.setAlignment_(NSCenterTextAlignment)
        content_view.addSubview_(self.hotkey_field)

        record_button = NSButton.alloc().initWithFrame_(NSMakeRect(360, 205, 70, 30))
        record_button.setTitle_("Record")
        record_button.setBezelStyle_(1)  # NSRoundedBezelStyle
        record_button.setTarget_(self)
        record_button.setAction_("recordHotkey:")
        content_view.addSubview_(record_button)

        # Language section
        language_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 170, 150, 20))
        language_label.setStringValue_("Language:")
        language_label.setBezeled_(False)
        language_label.setDrawsBackground_(False)
        language_label.setEditable_(False)
        language_label.setSelectable_(False)
        content_view.addSubview_(language_label)

        self.language_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(170, 165, 260, 30))
        self.language_popup.removeAllItems()
        # Add languages sorted by name
        sorted_languages = sorted(SUPPORTED_LANGUAGES.items(), key=lambda x: x[1])
        for lang_code, lang_name in sorted_languages:
            self.language_popup.addItemWithTitle_(lang_name)
            # Store language code as represented object
            item = self.language_popup.lastItem()
            item.setRepresentedObject_(lang_code)
        content_view.addSubview_(self.language_popup)

        # Auto-punctuation section
        self.auto_punctuation_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, 130, 410, 20))
        self.auto_punctuation_checkbox.setButtonType_(3)  # NSSwitchButton
        self.auto_punctuation_checkbox.setTitle_("Enable automatic punctuation")
        content_view.addSubview_(self.auto_punctuation_checkbox)

        # Info text
        info_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 60, 410, 50))
        info_label.setStringValue_(
            "Changes will take effect immediately after clicking Apply.\n"
            "Restart the app if changes don't apply."
        )
        info_label.setBezeled_(False)
        info_label.setDrawsBackground_(False)
        info_label.setEditable_(False)
        info_label.setSelectable_(False)
        info_label.setFont_(NSFont.systemFontOfSize_(11))
        info_label.setAlignment_(NSCenterTextAlignment)
        content_view.addSubview_(info_label)

        # Buttons
        cancel_button = NSButton.alloc().initWithFrame_(NSMakeRect(250, 20, 90, 30))
        cancel_button.setTitle_("Cancel")
        cancel_button.setBezelStyle_(1)
        cancel_button.setTarget_(self)
        cancel_button.setAction_("cancel:")
        content_view.addSubview_(cancel_button)

        apply_button = NSButton.alloc().initWithFrame_(NSMakeRect(350, 20, 80, 30))
        apply_button.setTitle_("Apply")
        apply_button.setBezelStyle_(1)
        apply_button.setKeyEquivalent_("\r")  # Enter key
        apply_button.setTarget_(self)
        apply_button.setAction_("apply:")
        content_view.addSubview_(apply_button)

        logger.debug("Preferences window created")

    def _load_preferences(self) -> None:
        """Load current preferences into UI."""
        try:
            # Load hotkey
            hotkey_config = self.preferences.get_hotkey_config()
            hotkey_str = self._format_hotkey(hotkey_config.keycode, hotkey_config.modifiers)
            self.hotkey_field.setStringValue_(hotkey_str)

            # Load language
            language = self.preferences.get(PreferenceKey.LANGUAGE)
            # Select the item with matching language code
            for i in range(self.language_popup.numberOfItems()):
                item = self.language_popup.itemAtIndex_(i)
                if item.representedObject() == language:
                    self.language_popup.selectItemAtIndex_(i)
                    break

            # Load auto-punctuation
            auto_punct = self.preferences.get(PreferenceKey.AUTO_PUNCTUATION)
            self.auto_punctuation_checkbox.setState_(1 if auto_punct else 0)

            logger.debug("Preferences loaded into UI")
        except Exception as e:
            logger.error(f"Failed to load preferences into UI: {e}")

    def _format_hotkey(self, keycode: int, modifiers: int) -> str:
        """
        Format hotkey for display.

        Args:
            keycode: Carbon keycode
            modifiers: Carbon modifier flags

        Returns:
            String representation of hotkey
        """
        # Common keycodes (macOS/Carbon keycodes)
        keycode_names = {
            # Special keys
            49: "Space",
            36: "Return",
            53: "Escape",
            51: "Delete",
            48: "Tab",
            117: "Delete Forward",
            # Function keys
            122: "F1", 120: "F2", 99: "F3", 118: "F4",
            96: "F5", 97: "F6", 98: "F7", 100: "F8",
            101: "F9", 109: "F10", 103: "F11", 111: "F12",
            # Letters
            0: "A", 11: "B", 8: "C", 2: "D", 14: "E", 3: "F", 5: "G", 4: "H",
            34: "I", 38: "J", 40: "K", 37: "L", 46: "M", 45: "N", 31: "O", 35: "P",
            12: "Q", 15: "R", 1: "S", 17: "T", 32: "U", 9: "V", 13: "W", 7: "X",
            16: "Y", 6: "Z",
            # Numbers
            29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5",
            22: "6", 26: "7", 28: "8", 25: "9",
            # Arrow keys
            123: "←", 124: "→", 125: "↓", 126: "↑",
        }

        # Modifier flags (Carbon)
        modifier_str = ""
        if modifiers & (1 << 8):  # cmdKey
            modifier_str += "⌘"
        if modifiers & (1 << 9):  # shiftKey
            modifier_str += "⇧"
        if modifiers & (1 << 11):  # optionKey
            modifier_str += "⌥"
        if modifiers & (1 << 12):  # controlKey
            modifier_str += "⌃"

        key_name = keycode_names.get(keycode, f"Key{keycode}")
        return f"{modifier_str}{key_name}"

    def recordHotkey_(self, sender) -> None:
        """Start recording a new hotkey."""
        logger.info("Recording hotkey...")
        self._recording_hotkey = True
        self._temp_hotkey_keycode = None
        self._temp_hotkey_modifiers = None

        # Update field to show recording state
        self.hotkey_field.setStringValue_("Press a key combination...")

        # Remove existing monitor if any
        self._stop_event_monitor()

        # Set up key event monitor
        def event_handler(event):
            if event.type() == NSKeyDown:
                keycode = event.keyCode()
                modifiers = event.modifierFlags()

                # Convert NSEvent modifiers to Carbon modifiers
                carbon_modifiers = 0
                if modifiers & NSCommandKeyMask:
                    carbon_modifiers |= (1 << 8)  # cmdKey
                if modifiers & NSShiftKeyMask:
                    carbon_modifiers |= (1 << 9)  # shiftKey
                if modifiers & NSAlternateKeyMask:
                    carbon_modifiers |= (1 << 11)  # optionKey
                if modifiers & NSControlKeyMask:
                    carbon_modifiers |= (1 << 12)  # controlKey

                # Store the hotkey
                self._temp_hotkey_keycode = keycode
                self._temp_hotkey_modifiers = carbon_modifiers

                # Update display
                hotkey_str = self._format_hotkey(keycode, carbon_modifiers)
                self.hotkey_field.setStringValue_(hotkey_str)

                # Stop recording
                self._recording_hotkey = False
                self._stop_event_monitor()

                logger.info(f"Hotkey captured: keycode={keycode}, modifiers={carbon_modifiers}")

                # Block this event from being processed further
                return None

            return event

        # Install local event monitor
        self._event_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, event_handler
        )
        logger.debug("Key event monitor installed")

    def _stop_event_monitor(self) -> None:
        """Stop and remove the key event monitor."""
        if self._event_monitor is not None:
            NSEvent.removeMonitor_(self._event_monitor)
            self._event_monitor = None
            logger.debug("Key event monitor removed")

    def apply_(self, sender) -> None:
        """Apply preferences and close window."""
        try:
            # Get hotkey config
            if self._temp_hotkey_keycode is not None:
                hotkey_config = HotkeyConfig(
                    keycode=self._temp_hotkey_keycode,
                    modifiers=self._temp_hotkey_modifiers or 0,
                )

                # Validate hotkey isn't conflicting with system shortcuts
                if not self._validate_hotkey(hotkey_config):
                    from Cocoa import NSAlert
                    alert = NSAlert.alloc().init()
                    alert.setMessageText_("Invalid Hotkey")
                    alert.setInformativeText_(
                        "This hotkey combination may conflict with system shortcuts. "
                        "Please choose a different combination."
                    )
                    alert.addButtonWithTitle_("OK")
                    alert.runModal()
                    return
            else:
                hotkey_config = self.preferences.get_hotkey_config()

            # Get language
            selected_item = self.language_popup.selectedItem()
            language = selected_item.representedObject() if selected_item else "en"

            # Get auto-punctuation
            auto_punct = bool(self.auto_punctuation_checkbox.state())

            # Save to preferences
            self.preferences.set_hotkey_config(hotkey_config, save=True)
            self.preferences.set(PreferenceKey.LANGUAGE, language, save=True)
            self.preferences.set(PreferenceKey.AUTO_PUNCTUATION, auto_punct, save=True)

            logger.info(f"Preferences applied: hotkey={hotkey_config}, language={language}, auto_punct={auto_punct}")

            # Notify callback
            if self.on_apply:
                try:
                    self.on_apply(hotkey_config, auto_punct, language)
                except Exception as e:
                    logger.error(f"Error in on_apply callback: {e}")

            # Clean up and close window
            self._stop_event_monitor()
            self.window.close()

        except Exception as e:
            logger.error(f"Failed to apply preferences: {e}")
            # Show error alert
            from Cocoa import NSAlert
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Error")
            alert.setInformativeText_(f"Failed to apply preferences: {e}")
            alert.addButtonWithTitle_("OK")
            alert.runModal()

    def _validate_hotkey(self, config: HotkeyConfig) -> bool:
        """
        Validate hotkey configuration to avoid conflicts.

        Args:
            config: Hotkey configuration to validate

        Returns:
            True if valid, False if conflicts detected
        """
        # Common system shortcuts to avoid (examples)
        # These are Carbon modifier flags: cmdKey=256, shiftKey=512, optionKey=2048, controlKey=4096
        conflicting_combinations = [
            # Cmd+Space (Spotlight)
            (49, 256),
            # Cmd+Tab (App Switcher)
            (48, 256),
            # Cmd+Q (Quit)
            (12, 256),
        ]

        for keycode, modifiers in conflicting_combinations:
            if config.keycode == keycode and config.modifiers == modifiers:
                logger.warning(f"Hotkey conflict detected: keycode={keycode}, modifiers={modifiers}")
                return False

        return True

    def cancel_(self, sender) -> None:
        """Cancel and close window."""
        logger.info("Preferences cancelled")
        self._stop_event_monitor()
        self.window.close()


def show_about_panel() -> None:
    """Show the About panel."""
    from Cocoa import NSAlert
    import toml
    from pathlib import Path

    try:
        # Read version from pyproject.toml
        project_root = Path(__file__).parent.parent.parent
        pyproject_path = project_root / "pyproject.toml"

        version = "unknown"
        if pyproject_path.exists():
            pyproject_data = toml.load(pyproject_path)
            version = pyproject_data.get("tool", {}).get("poetry", {}).get("version", "unknown")

        # Show about alert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("About Whisper Input")
        alert.setInformativeText_(
            f"Whisper Input for macOS\n"
            f"Version: {version}\n\n"
            f"On-device speech-to-text using Whisper MLX.\n"
            f"Press and hold to record, release to transcribe.\n\n"
            f"© 2024"
        )
        alert.addButtonWithTitle_("OK")
        alert.runModal()

    except Exception as e:
        logger.error(f"Failed to show about panel: {e}")
        # Fallback alert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("About Whisper Input")
        alert.setInformativeText_("Whisper Input for macOS\nOn-device speech-to-text")
        alert.addButtonWithTitle_("OK")
        alert.runModal()
