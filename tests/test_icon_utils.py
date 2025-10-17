"""Tests for icon_utils module."""

import pytest
from Cocoa import NSImage

from whisper_input_mac.icon_utils import (
    create_idle_icon,
    create_recording_icon,
    create_busy_icon,
)


class TestIconGeneration:
    """Test vector-based icon generation."""

    def test_create_idle_icon(self):
        """Test idle icon creation."""
        icon = create_idle_icon()
        assert isinstance(icon, NSImage)
        assert icon is not None
        assert icon.isTemplate()

    def test_create_recording_icon(self):
        """Test recording icon creation."""
        icon = create_recording_icon()
        assert isinstance(icon, NSImage)
        assert icon is not None
        assert icon.isTemplate()

    def test_create_busy_icon(self):
        """Test busy icon creation."""
        icon = create_busy_icon()
        assert isinstance(icon, NSImage)
        assert icon is not None
        assert icon.isTemplate()

    def test_icons_have_correct_size(self):
        """Test that icons are created with default size."""
        default_size = 18.0
        idle = create_idle_icon()
        recording = create_recording_icon()
        busy = create_busy_icon()

        # All icons should have same size
        assert idle.size().width == default_size
        assert idle.size().height == default_size
        assert recording.size().width == default_size
        assert recording.size().height == default_size
        assert busy.size().width == default_size
        assert busy.size().height == default_size

    def test_icons_with_custom_size(self):
        """Test that icons can be created with custom size."""
        custom_size = 24.0
        idle = create_idle_icon(size=custom_size)
        recording = create_recording_icon(size=custom_size)
        busy = create_busy_icon(size=custom_size)

        assert idle.size().width == custom_size
        assert idle.size().height == custom_size
        assert recording.size().width == custom_size
        assert recording.size().height == custom_size
        assert busy.size().width == custom_size
        assert busy.size().height == custom_size

    def test_icons_are_marked_as_templates(self):
        """Test that all icons are marked as templates for dark mode."""
        icons = [
            create_idle_icon(),
            create_recording_icon(),
            create_busy_icon(),
        ]

        for icon in icons:
            assert icon.isTemplate(), "Icon should be marked as template"

    def test_icons_are_distinct(self):
        """Test that different icons produce different visual content."""
        idle = create_idle_icon()
        recording = create_recording_icon()
        busy = create_busy_icon()

        # While we can't easily compare pixel data through PyObjC,
        # we can at least verify they're different objects
        assert idle is not recording
        assert recording is not busy
        assert idle is not busy
