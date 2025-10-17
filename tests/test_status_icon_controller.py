"""Tests for status_icon_controller module."""

import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock

from whisper_input_mac.status_icon_controller import (
    IconState,
    StatusIconController,
)


class TestIconState:
    """Test IconState enum."""

    def test_icon_state_values(self):
        """Test that IconState has all required states."""
        assert IconState.IDLE.value == "idle"
        assert IconState.RECORDING.value == "recording"
        assert IconState.BUSY.value == "busy"

    def test_icon_state_enum_members(self):
        """Test that all expected enum members exist."""
        states = {state.value for state in IconState}
        assert states == {"idle", "recording", "busy"}


class TestStatusIconController:
    """Test StatusIconController class."""

    def test_controller_initialization(self):
        """Test controller initializes with correct default state."""
        controller = StatusIconController()

        assert controller.current_state == IconState.IDLE
        assert controller.status_item is not None
        assert controller.status_button is not None
        assert controller.icons is not None
        assert len(controller.icons) == 3

    def test_icon_caching(self):
        """Test that icons are cached."""
        controller = StatusIconController()

        # All three icons should be cached
        assert IconState.IDLE in controller.icons
        assert IconState.RECORDING in controller.icons
        assert IconState.BUSY in controller.icons

        # Icons should be the same instances
        idle1 = controller.icons[IconState.IDLE]
        idle2 = controller.icons[IconState.IDLE]
        assert idle1 is idle2

    def test_menu_setup(self):
        """Test that menu is properly set up."""
        controller = StatusIconController()

        menu = controller.status_item.menu()
        assert menu is not None
        assert menu.numberOfItems() > 0

    def test_set_state_immediate_changes_state(self):
        """Test that _set_state_immediate updates the current state."""
        controller = StatusIconController()

        controller._set_state_immediate(IconState.RECORDING)
        assert controller.current_state == IconState.RECORDING

        controller._set_state_immediate(IconState.BUSY)
        assert controller.current_state == IconState.BUSY

        controller._set_state_immediate(IconState.IDLE)
        assert controller.current_state == IconState.IDLE

    def test_set_state_immediate_updates_tooltip(self):
        """Test that tooltip is updated on state change."""
        controller = StatusIconController()
        button = controller.status_button

        controller._set_state_immediate(IconState.IDLE)
        assert "Ready" in button.toolTip()

        controller._set_state_immediate(IconState.RECORDING)
        assert "Recording" in button.toolTip()

        controller._set_state_immediate(IconState.BUSY)
        assert "Transcribing" in button.toolTip()

    def test_set_state_immediate_updates_icon(self):
        """Test that icon is updated on state change."""
        controller = StatusIconController()
        button = controller.status_button

        idle_icon = controller.icons[IconState.IDLE]
        recording_icon = controller.icons[IconState.RECORDING]
        busy_icon = controller.icons[IconState.BUSY]

        controller._set_state_immediate(IconState.IDLE)
        assert button.image() is idle_icon

        controller._set_state_immediate(IconState.RECORDING)
        assert button.image() is recording_icon

        controller._set_state_immediate(IconState.BUSY)
        assert button.image() is busy_icon

    def test_enter_recording(self):
        """Test enter_recording helper."""
        controller = StatusIconController()

        controller.enter_recording()
        assert controller.current_state == IconState.RECORDING

    def test_exit_recording(self):
        """Test exit_recording helper."""
        controller = StatusIconController()

        controller.enter_recording()
        assert controller.current_state == IconState.RECORDING

        controller.exit_recording()
        assert controller.current_state == IconState.IDLE

    def test_set_busy(self):
        """Test set_busy helper."""
        controller = StatusIconController()

        controller.set_busy()
        assert controller.current_state == IconState.BUSY

    def test_set_idle(self):
        """Test set_idle helper."""
        controller = StatusIconController()

        controller.set_busy()
        assert controller.current_state == IconState.BUSY

        controller.set_idle()
        assert controller.current_state == IconState.IDLE

    def test_spinner_starts_on_busy(self):
        """Test that spinner starts when entering busy state."""
        controller = StatusIconController()

        assert controller._spinner is None

        controller._set_state_immediate(IconState.BUSY)
        assert controller._spinner is not None
        assert controller._spinner.isIndeterminate()

    def test_spinner_stops_on_idle(self):
        """Test that spinner stops when leaving busy state."""
        controller = StatusIconController()

        controller._set_state_immediate(IconState.BUSY)
        assert controller._spinner is not None

        controller._set_state_immediate(IconState.IDLE)
        assert controller._spinner is None

    def test_spinner_stops_on_recording(self):
        """Test that spinner stops when transitioning to recording."""
        controller = StatusIconController()

        controller._set_state_immediate(IconState.BUSY)
        assert controller._spinner is not None

        controller._set_state_immediate(IconState.RECORDING)
        assert controller._spinner is None

    def test_debounce_delay_configuration(self):
        """Test debounce delay can be configured."""
        controller = StatusIconController()

        assert controller._debounce_delay == 0.1

        controller._debounce_delay = 0.2
        assert controller._debounce_delay == 0.2


class TestStatusIconControllerAsync:
    """Test async behavior of StatusIconController."""

    @pytest.mark.asyncio
    async def test_debounced_set_state(self):
        """Test that debounced state changes work correctly."""
        controller = StatusIconController()

        await controller._debounced_set_state(IconState.RECORDING)
        await asyncio.sleep(0.15)

        assert controller.current_state == IconState.RECORDING

    @pytest.mark.asyncio
    async def test_debounce_cancels_previous_task(self):
        """Test that new debounce requests cancel previous ones."""
        controller = StatusIconController()

        # Rapid state changes
        await controller._debounced_set_state(IconState.RECORDING)
        await controller._debounced_set_state(IconState.BUSY)
        await controller._debounced_set_state(IconState.IDLE)

        # Wait for final debounce
        await asyncio.sleep(0.15)

        # Should end up in final state (idle)
        assert controller.current_state == IconState.IDLE

    def test_set_state_without_event_loop(self):
        """Test set_state can be called without running event loop."""
        controller = StatusIconController()

        # This should not raise an error
        controller.set_state(IconState.RECORDING)
        # State is set immediately when no event loop
        assert controller.current_state == IconState.RECORDING

    @pytest.mark.asyncio
    async def test_set_state_with_event_loop(self):
        """Test set_state with running event loop uses debouncing."""
        controller = StatusIconController()

        controller.set_state(IconState.RECORDING)
        controller.set_state(IconState.BUSY)

        await asyncio.sleep(0.15)

        # Should end up in busy state due to debouncing
        assert controller.current_state == IconState.BUSY


class TestStatusButtonReference:
    """Test status button reference management."""

    def test_status_button_reference_preserved(self):
        """Test that button reference is kept alive on controller."""
        controller = StatusIconController()

        button1 = controller.status_button
        button2 = controller.status_button

        # Should return the same button
        assert button1 is button2

    def test_menu_item_quit_present(self):
        """Test that Quit menu item is present."""
        controller = StatusIconController()

        menu = controller.status_item.menu()
        quit_item = None

        for i in range(menu.numberOfItems()):
            item = menu.itemAtIndex_(i)
            if "Quit" in item.title():
                quit_item = item
                break

        assert quit_item is not None
