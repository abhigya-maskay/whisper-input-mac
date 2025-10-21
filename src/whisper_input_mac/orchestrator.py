import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from .audio_capture_service import AudioCaptureService
from .status_icon_controller import StatusIconController, IconState
from .transcription import LightningWhisperTranscriber, TranscriptionConfig, TranscriptionError
from .accessibility import FocusObserver, wait_for_trusted_access, AccessibilityPermissionError
from .text_injector import TextInjector
from .permissions import PermissionsCoordinator, PermissionState
from .preferences import PreferencesStore, PreferenceKey

logger = logging.getLogger(__name__)


class TranscriptionOrchestrator:
    """Orchestrates recording, transcription, and UI state management."""

    def __init__(
        self,
        audio_service: AudioCaptureService,
        icon_controller: StatusIconController,
        permissions_coordinator: Optional[PermissionsCoordinator] = None,
        preferences_store: Optional[PreferencesStore] = None,
        transcriber: Optional[LightningWhisperTranscriber] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            audio_service: AudioCaptureService instance for recording
            icon_controller: StatusIconController for UI updates
            permissions_coordinator: PermissionsCoordinator instance (optional)
            preferences_store: PreferencesStore instance (optional)
            transcriber: LightningWhisperTranscriber instance (created if not provided)
        """
        self.audio_service = audio_service
        self.icon_controller = icon_controller
        self.permissions_coordinator = permissions_coordinator
        self.preferences_store = preferences_store
        self._current_session_id: Optional[str] = None
        self._is_processing = False

        # Create transcriber with config from preferences
        if transcriber:
            self.transcriber = transcriber
        else:
            config = self._create_transcription_config()
            self.transcriber = LightningWhisperTranscriber(config=config)

        # Register preference change listener to reload transcriber when language changes
        if self.preferences_store:
            self.preferences_store.add_change_listener(self._on_preference_changed)

        # Queue for emitting injection events to downstream components
        self.injection_events: asyncio.Queue = asyncio.Queue()

        # Initialize focus observer for tracking focused UI element
        try:
            self.focus_observer = FocusObserver()
            logger.debug("FocusObserver initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize FocusObserver: {e}")
            self.focus_observer = None

        # Initialize text injector for sending transcribed text
        try:
            self.text_injector = TextInjector(restore_clipboard=True)
            logger.debug("TextInjector initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize TextInjector: {e}")
            self.text_injector = None

    async def startup_permissions_check(self):
        """
        Check and request necessary permissions during startup.

        This method checks both microphone and accessibility permissions,
        prompting the user to grant them if needed.
        """
        logger.info("Checking permissions at startup...")

        # Use PermissionsCoordinator if available
        if self.permissions_coordinator:
            try:
                await self.permissions_coordinator.ensure_ready(show_dialogs=True)
                logger.info("All permissions granted via PermissionsCoordinator")
            except PermissionError as e:
                logger.warning(f"Permission check failed: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error during permission check: {e}")
            return

        # Fallback to legacy permission checking
        logger.warning("PermissionsCoordinator not available, using legacy permission checks")

        # Check microphone permission
        try:
            await self.audio_service.ensure_microphone_permission()
            logger.info("Microphone permission granted")
        except Exception as e:
            logger.warning(f"Microphone permission check failed: {e}")

        # Check accessibility permission
        if self.focus_observer:
            try:
                # First, trigger the system prompt if not already trusted
                loop = asyncio.get_running_loop()
                is_trusted = await loop.run_in_executor(
                    None, self.focus_observer.ensure_trusted, True
                )

                if is_trusted:
                    logger.info("Accessibility permission already granted")
                else:
                    # Wait for user to grant permission after seeing the prompt
                    logger.info("Waiting for accessibility permission...")
                    has_access = await wait_for_trusted_access(
                        self.focus_observer,
                        timeout=30.0,  # Give user time to navigate to Settings
                        poll_interval=0.5
                    )
                    if has_access:
                        logger.info("Accessibility permission granted")
                    else:
                        logger.warning(
                            "Accessibility permission not granted. "
                            "Focus tracking will be limited. "
                            "Please enable accessibility access in System Preferences."
                        )
            except AccessibilityPermissionError as e:
                logger.warning(f"Accessibility permission check failed: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error checking accessibility permission: {e}")

    async def handle_press_lifecycle(self):
        """
        Listen to press events from the icon controller and manage recording/transcription.

        This method should be run as a background task to continuously process press events.
        """
        try:
            while True:
                event = await self.icon_controller.press_events.get()
                await self._handle_press_event(event)
        except asyncio.CancelledError:
            logger.debug("Press lifecycle handler cancelled")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in press lifecycle handler: {e}", exc_info=True)

    async def _handle_press_event(self, event: dict):
        """
        Handle a single press lifecycle event.

        Args:
            event: Event dict with keys 'type', etc.
        """
        event_type = event.get("type")
        logger.info(f"Processing press event: {event_type}")

        if event_type == "press_started":
            await self._on_press_started()
        elif event_type == "hold_started":
            await self._on_hold_started()
        elif event_type == "press_released":
            await self._on_press_released()
        else:
            logger.warning(f"Unknown press event type: {event_type}")

    async def _on_press_started(self):
        """Handle initial press (no action yet, waiting for hold threshold)."""
        logger.debug("Press started")

    async def _on_hold_started(self):
        """Start recording when hold threshold is reached."""
        if self._is_processing:
            logger.warning("Already processing, ignoring hold_started")
            return

        self._current_session_id = str(uuid.uuid4())
        logger.info(f"Starting recording session: {self._current_session_id}")

        try:
            # Check permissions before recording
            if self.permissions_coordinator:
                # Use PermissionsCoordinator to gate recording
                try:
                    await self.permissions_coordinator.ensure_ready(show_dialogs=False)
                    logger.debug("Permissions verified, starting recording")
                except PermissionError as e:
                    logger.error(f"Permission denied: {e}")
                    self.icon_controller.set_idle()

                    # Show user-facing error dialog
                    self.icon_controller.show_permission_error(str(e))
                    return
            else:
                # Fallback to legacy permission check
                await self.audio_service.ensure_microphone_permission()

            # Start recording
            self.audio_service.start_recording(self._current_session_id)
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self.icon_controller.set_idle()

    async def _on_press_released(self):
        """Stop recording and transcribe audio."""
        if not self._current_session_id:
            logger.debug("No active recording session to stop")
            return

        session_id = self._current_session_id
        self._current_session_id = None
        self._is_processing = True

        try:
            # Stop recording
            audio_path = self.audio_service.stop_recording(session_id)
            if not audio_path:
                logger.error("Failed to stop recording")
                self.icon_controller.set_idle()
                return

            logger.info(f"Recording stopped, file: {audio_path}")

            # Update UI to busy state for transcription
            self.icon_controller.set_busy()

            # Transcribe asynchronously
            logger.info("Starting transcription...")
            result = await self.transcriber.transcribe_audio(Path(audio_path))

            # Extract text
            transcribed_text = result.get("text", "")
            logger.info(f"Transcription complete: {len(transcribed_text)} characters")

            # Apply auto-punctuation if enabled
            transcribed_text = self._apply_auto_punctuation(transcribed_text)

            # Log focused element metadata for debugging
            if self.focus_observer:
                try:
                    focused_info = self.focus_observer.get_focused_element()
                    if focused_info:
                        logger.debug(
                            f"Focused app - Bundle: {focused_info.bundle_identifier}, "
                            f"Role: {focused_info.role}, Subrole: {focused_info.subrole}"
                        )
                except AccessibilityPermissionError:
                    logger.debug("Accessibility permission not available for focus tracking")
                except Exception as e:
                    logger.debug(f"Failed to get focused element info: {e}")

            if transcribed_text:
                # Inject transcribed text to active application
                if self.text_injector:
                    # Use clipboard method for better compatibility (especially with terminals)
                    success, error_msg = self.text_injector.send_text(transcribed_text, prefer_clipboard=True)
                    if success:
                        logger.info(f"Text injected successfully: {len(transcribed_text)} characters")
                        # Emit success event for downstream components
                        await self.injection_events.put({
                            "type": "injection_success",
                            "session_id": session_id,
                            "text": transcribed_text,
                            "char_count": len(transcribed_text),
                        })
                    else:
                        logger.error(f"Text injection failed: {error_msg}")
                        # Emit failure event for downstream components
                        await self.injection_events.put({
                            "type": "injection_failure",
                            "session_id": session_id,
                            "text": transcribed_text,
                            "char_count": len(transcribed_text),
                            "error_message": error_msg,
                        })
                else:
                    logger.warning("TextInjector not available, skipping text injection")
                    # Emit failure event when injector is not available
                    await self.injection_events.put({
                        "type": "injection_failure",
                        "session_id": session_id,
                        "text": transcribed_text,
                        "char_count": len(transcribed_text),
                        "error_message": "TextInjector not available",
                    })
            else:
                logger.warning("Empty transcription result")
                # Emit failure event for empty transcription
                await self.injection_events.put({
                    "type": "injection_failure",
                    "session_id": session_id,
                    "text": "",
                    "char_count": 0,
                    "error_message": "Empty transcription result",
                })

            # Reset UI
            self.icon_controller.set_idle()

        except TranscriptionError as e:
            logger.warning(f"Transcription failed: {e}")
            self.icon_controller.set_idle()
        except Exception as e:
            logger.error(f"Unexpected error during transcription: {e}", exc_info=True)
            self.icon_controller.set_idle()
        finally:
            self._is_processing = False


    def _on_preference_changed(self, key: PreferenceKey, new_value) -> None:
        """
        Handle preference changes.

        Args:
            key: The preference key that changed
            new_value: The new value
        """
        # Reload transcriber when language changes
        if key == PreferenceKey.LANGUAGE:
            logger.info(f"Language preference changed to: {new_value}, reloading transcriber")
            self.reload_transcriber()
        # Auto-punctuation changes don't require transcriber reload
        elif key == PreferenceKey.AUTO_PUNCTUATION:
            logger.info(f"Auto-punctuation preference changed to: {new_value}")

    def _create_transcription_config(self) -> TranscriptionConfig:
        """
        Create transcription config from preferences.

        Returns:
            TranscriptionConfig instance with settings from PreferencesStore
        """
        config = TranscriptionConfig()

        # Read language preference
        if self.preferences_store:
            try:
                language = self.preferences_store.get(PreferenceKey.LANGUAGE)
                config.language = language if language != "en" else None  # None = auto-detect
                logger.debug(f"Using language from preferences: {language}")
            except Exception as e:
                logger.warning(f"Failed to read language preference: {e}")

        return config

    def reload_transcriber(self) -> None:
        """
        Reload the transcriber with updated configuration from preferences.

        This should be called when language or other transcription preferences change.
        """
        try:
            # Shutdown old transcriber
            if self.transcriber:
                self.transcriber.shutdown()

            # Create new transcriber with updated config
            config = self._create_transcription_config()
            self.transcriber = LightningWhisperTranscriber(config=config)
            logger.info("Transcriber reloaded with updated preferences")
        except Exception as e:
            logger.error(f"Failed to reload transcriber: {e}")

    def _apply_auto_punctuation(self, text: str) -> str:
        """
        Apply automatic punctuation to transcribed text.

        Args:
            text: Raw transcribed text

        Returns:
            Text with auto-punctuation applied
        """
        if not text:
            return text

        # Check if auto-punctuation is enabled
        if self.preferences_store:
            try:
                auto_punct = self.preferences_store.get(PreferenceKey.AUTO_PUNCTUATION)
                if not auto_punct:
                    return text
            except Exception as e:
                logger.warning(f"Failed to read auto-punctuation preference: {e}")
                return text

        # Basic auto-punctuation rules
        processed = text.strip()

        # Capitalize first letter
        if processed:
            processed = processed[0].upper() + processed[1:]

        # Add period at end if no punctuation exists
        if processed and processed[-1] not in '.!?':
            processed += '.'

        logger.debug(f"Applied auto-punctuation: '{text}' -> '{processed}'")
        return processed

    def shutdown(self):
        """Clean up resources."""
        # Remove preference change listener
        if self.preferences_store:
            self.preferences_store.remove_change_listener(self._on_preference_changed)

        if self._current_session_id:
            self.audio_service.cancel_recording()
        self.transcriber.shutdown()
        logger.debug("Orchestrator shutdown complete")
